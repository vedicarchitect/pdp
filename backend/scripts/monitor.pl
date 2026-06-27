#!/usr/bin/perl
# monitor.pl — PDP SuperTrend strategy live monitor (read-only client)
# Polls Redis + FastAPI every second. Zero side-effects — all logic stays in FastAPI.
#
# Usage:  perl monitor.pl
#
# Deps: LWP::UserAgent, JSON, IO::Socket::INET, Time::HiRes  (all standard)

use strict;
use warnings;
use IO::Socket::INET;
use LWP::UserAgent;
use JSON qw(decode_json);
use POSIX qw(floor);
use Time::HiRes qw(sleep time);
use Scalar::Util qw(looks_like_number);

# ── Config ─────────────────────────────────────────────────────────────────
my $REDIS_HOST  = '127.0.0.1';
my $REDIS_PORT  = 6379;
my $API_BASE    = 'http://localhost:8000';
my $NIFTY_SID   = '13';
my $TF          = '5m';
my $POLL_SEC    = 1;
my $CHAIN_TTL   = 10;      # re-fetch chain every N seconds
my $LEG_STOP_PER_LOT_DEFAULT = 1000.0;  # fallback if strategy params unavailable
my $DAY_STOP_DEFAULT         = 10000.0;
my $STOP_ALERT_FRAC          = 0.30;    # warn when < 30% of stop budget remains

# ── RESP mini-client ────────────────────────────────────────────────────────
my $redis;
sub redis_connect {
    $redis = IO::Socket::INET->new(
        PeerAddr => $REDIS_HOST, PeerPort => $REDIS_PORT,
        Proto => 'tcp', Timeout => 2,
    ) or die "Cannot connect to Redis $REDIS_HOST:$REDIS_PORT: $!\n";
    $redis->autoflush(1);
}

sub _send_cmd {
    my @args = @_;
    my $msg = '*' . scalar(@args) . "\r\n";
    for my $a (@args) {
        $msg .= '$' . length($a) . "\r\n" . $a . "\r\n";
    }
    print $redis $msg;
}

sub _read_resp {
    my $line = <$redis>;
    return undef unless defined $line;
    $line =~ s/\r\n$//;
    my $type = substr($line, 0, 1);
    my $rest = substr($line, 1);
    if ($type eq '+') { return $rest; }
    if ($type eq '-') { return undef; }
    if ($type eq ':') { return int($rest); }
    if ($type eq '$') {
        my $len = int($rest);
        return undef if $len == -1;
        my $buf = '';
        while (length($buf) < $len + 2) {
            my $chunk;
            $redis->read($chunk, $len + 2 - length($buf));
            last unless defined $chunk;
            $buf .= $chunk;
        }
        $buf =~ s/\r\n$//;
        return $buf;
    }
    if ($type eq '*') {
        my $n = int($rest);
        return undef if $n == -1;
        return [ map { _read_resp() } 1..$n ];
    }
    return undef;
}

sub redis_get {
    my ($key) = @_;
    _send_cmd('GET', $key);
    return _read_resp();
}

# ── HTTP helper ─────────────────────────────────────────────────────────────
my $ua = LWP::UserAgent->new(timeout => 3, agent => 'PDP-monitor/1.0');
sub api_get {
    my ($path, %params) = @_;
    my $url = $API_BASE . $path;
    if (%params) {
        $url .= '?' . join('&', map { "$_=$params{$_}" } sort keys %params);
    }
    my $r = $ua->get($url);
    return undef unless $r->is_success;
    return eval { decode_json($r->decoded_content) };
}

# ── Expiry helpers ──────────────────────────────────────────────────────────
sub next_weekly_expiry {
    # NIFTY weekly expiry = Tuesday. Use today if Tuesday before market close
    # (15:30 IST = 10:00 UTC); otherwise compute the next Tuesday.
    my $now  = time();
    my @t    = gmtime($now);
    my $wday = $t[6];  # 0=Sun 2=Tue 6=Sat
    my $days_ahead;
    if ($wday == 2 && $t[2] < 10) {
        $days_ahead = 0;
    } else {
        $days_ahead = (2 - $wday + 7) % 7;
        $days_ahead = 7 if $days_ahead == 0;
    }
    my @exp = gmtime($now + $days_ahead * 86400);
    return sprintf('%04d-%02d-%02d', $exp[5]+1900, $exp[4]+1, $exp[3]);
}

sub expiry_label {
    my $exp = shift // '';
    return 'Exp?' unless $exp =~ /^\d{4}-(\d{2})-(\d{2})$/;
    my @MON = qw(Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec);
    return $MON[$1 - 1] . ($2 + 0);
}

# ── Formatting ───────────────────────────────────────────────────────────────
my $R = "\e[0m";
sub bold  { "\e[1m$_[0]$R" }
sub cyan  { "\e[1;36m$_[0]$R" }
sub grey  { "\e[90m$_[0]$R" }
sub green { "\e[32m$_[0]$R" }
sub red   { "\e[31m$_[0]$R" }
sub yel   { "\e[33m$_[0]$R" }

sub fp { my $v = shift; my $f = shift // '%.2f'; return (defined $v && looks_like_number($v)) ? sprintf($f, $v) : '  --  ' }
sub fdir { my $d = shift; return !defined($d) ? grey('  -- ') : $d > 0 ? green('▲ UP') : red('▼ DN') }
sub fg { my $v = shift; my $f = shift // '%+.4f'; return (defined $v && looks_like_number($v)) ? sprintf($f, $v) : '  --  ' }
sub fpnl {
    my $v = shift;
    return grey('   --  ') unless defined $v && looks_like_number($v);
    return $v >= 0 ? green(sprintf('%+9.2f', $v)) : red(sprintf('%+9.2f', $v));
}

sub cls  { print "\033[H\033[2J" }
sub ist_time {
    # Convert UTC epoch to IST (+5:30)
    my $t = shift // time();
    my $ist = $t + 5*3600 + 30*60;
    my @v = gmtime($ist);
    return sprintf('%02d:%02d:%02d', $v[2], $v[1], $v[0]);
}

# Convert an ISO-8601 UTC string like "2026-06-08T07:50:00.123456+00:00"
# or "2026-06-08T07:50:00+00:00" to an IST time string "HH:MM:SS IST".
sub utc_to_ist {
    my $s = shift // '';
    return '--' unless $s =~ /T(\d{2}):(\d{2}):(\d{2})/;
    my ($h, $m, $sec) = ($1 + 0, $2 + 0, $3 + 0);
    $m += 30; if ($m >= 60) { $m -= 60; $h++ }
    $h += 5;  if ($h >= 24) { $h -= 24 }
    return sprintf('%02d:%02d:%02d IST', $h, $m, $sec);
}

# Convert just HH:MM from a UTC bar_time string to IST HH:MM
sub bar_utc_to_ist {
    my $s = shift // '';
    return '--' unless $s =~ /T(\d{2}):(\d{2})/;
    my ($h, $m) = ($1 + 0, $2 + 0);
    $m += 30; if ($m >= 60) { $m -= 60; $h++ }
    $h += 5;  if ($h >= 24) { $h -= 24 }
    return sprintf('%02d:%02d IST', $h, $m);
}

# ── State ────────────────────────────────────────────────────────────────────
my %chain_cache;
my $chain_ts     = 0;
my $prev_dir     = undef;
my $CHAIN_EXPIRY = next_weekly_expiry();
my $last_date    = '';

# ── Main ─────────────────────────────────────────────────────────────────────
redis_connect();
cls();
print "\e[?25l";   # hide cursor
$SIG{INT}  = sub { print "\e[?25h\n$R"; exit 0 };
$SIG{TERM} = $SIG{INT};

my $tick = 0;
while (1) {
    my $t0 = time();
    $tick++;

    # ── Date rollover: recompute expiry when the calendar day changes ────
    {
        my @td = gmtime($t0);
        my $today = sprintf('%04d%02d%02d', $td[5]+1900, $td[4]+1, $td[3]);
        if ($today ne $last_date) {
            $last_date    = $today;
            $CHAIN_EXPIRY = next_weekly_expiry();
            $chain_ts     = 0;   # force chain refresh on new expiry
        }
    }

    # ── Redis reads ───────────────────────────────────────────────────────
    my $nifty_ltp_s = redis_get("ltp:$NIFTY_SID") // '0';
    my $st_raw      = redis_get("st:$NIFTY_SID:$TF");

    # Reconnect on Redis drop (both the probe and reconnect wrapped in eval)
    unless (defined $st_raw || defined eval { redis_get("ltp:$NIFTY_SID") }) {
        eval { redis_connect() };
    }

    my $st = undef;
    if ($st_raw) {
        eval { $st = decode_json($st_raw) };
    }

    # ── Positions ─────────────────────────────────────────────────────────
    my $pos_data = api_get('/api/v1/portfolio/positions');
    my @positions = $pos_data ? @{ $pos_data->{positions} // [] } : ();
    my ($pos) = grep { ($_->{exchange_segment}//'') eq 'NSE_FNO' && ($_->{net_qty}//0) < 0 } @positions;

    # ── Orders + Trades (fill price per leg) ──────────────────────────────
    my $orders_raw = api_get('/api/v1/orders', today => 1) // [];
    my @orders = @$orders_raw;
    my $trades_raw = api_get('/api/v1/trades', today => 1) // [];
    # Build map: order_id -> fill_price
    my %fill_px;
    for my $t (@$trades_raw) {
        $fill_px{ $t->{order_id} } = $t->{fill_price} + 0 if defined $t->{fill_price};
    }

    # ── Option LTP from Redis ─────────────────────────────────────────────
    my $opt_sid = $pos ? $pos->{security_id} : '';
    my $opt_ltp_s = $opt_sid ? (redis_get("ltp:$opt_sid") // '0') : '0';

    # ── Options chain refresh ─────────────────────────────────────────────
    my $now = time();
    if ($now - $chain_ts >= $CHAIN_TTL) {
        my $chain = api_get("/api/v1/options/NIFTY/chain", expiry => $CHAIN_EXPIRY);
        if ($chain && ref($chain->{strikes}) eq 'ARRAY') {
            %chain_cache = ();
            for my $row (@{ $chain->{strikes} }) {
                $chain_cache{ $row->{strike} } = $row;
            }
            $chain_ts = $now;
        }
    }

    # ── Strategy status ───────────────────────────────────────────────────
    my $strats    = api_get('/api/v1/strategies') // [];
    my ($strat)   = grep { ($_->{id}//'') eq 'supertrend_short' } @$strats;

    # ── Portfolio summary ─────────────────────────────────────────────────
    my $summary   = api_get('/api/v1/portfolio/summary');

    # ── Derive computed values ────────────────────────────────────────────
    my $nifty_ltp = looks_like_number($nifty_ltp_s) ? $nifty_ltp_s + 0 : 0;
    my $opt_ltp   = looks_like_number($opt_ltp_s)   ? $opt_ltp_s + 0   : 0;

    my $st_dir     = $st ? $st->{direction}  : undef;
    my $st_val     = $st ? $st->{value}      : undef;
    my $st_bar     = $st ? $st->{bar_time}   : undef;
    my $st_flipped = $st ? ($st->{flipped} ? 1 : 0) : 0;

    # Detect direction flip across polls (even between bar closes)
    my $flip_alert = (defined $st_dir && defined $prev_dir && $st_dir != $prev_dir) ? 1 : 0;
    $prev_dir = $st_dir;

    # Determine expected option type from ST
    my $exp_type   = (defined $st_dir && $st_dir < 0) ? 'ce' : 'pe';
    my $exp_strike = $nifty_ltp ? int(($nifty_ltp + ($exp_type eq 'ce' ? 50 : -50)) / 50 + 0.5) * 50 : 0;

    # Greeks from chain
    my ($g_delta, $g_gamma, $g_theta, $g_vega, $g_iv, $chain_ltp) = (undef) x 6;
    my $actual_strike = $exp_strike;
    if ($exp_strike && exists $chain_cache{$exp_strike}) {
        my $leg  = $chain_cache{$exp_strike}{$exp_type} // {};
        $chain_ltp = $leg->{ltp};
        $g_delta   = $leg->{delta};
        $g_gamma   = $leg->{gamma};
        $g_theta   = $leg->{theta};
        $g_vega    = $leg->{vega};
        $g_iv      = defined($leg->{iv}) ? $leg->{iv} * 100 : undef;
    }
    # If Redis hasn't got a tick yet, use chain LTP
    $opt_ltp = $chain_ltp if (!$opt_ltp && $chain_ltp);

    # Live unrealized P&L (short sell: profit when price falls)
    my $lots    = $pos ? int(abs($pos->{net_qty}) / 65 + 0.5) : 0;
    my $avg_px  = $pos ? ($pos->{avg_price} + 0) : undef;
    my $qty     = $pos ? abs($pos->{net_qty}) : 0;
    # Prefer Redis LTP (real-time), fall back to chain LTP (refreshed every $CHAIN_TTL s)
    my $ltp_for_pnl = ($opt_ltp && $opt_ltp > 0) ? $opt_ltp : ($chain_ltp // 0);
    my $unreal  = ($qty && $ltp_for_pnl && $avg_px) ? ($avg_px - $ltp_for_pnl) * $qty : ($pos ? $pos->{unrealized_pnl} : undef);
    my $ltp_src = ($opt_ltp && $opt_ltp > 0) ? 'live' : ($chain_ltp ? 'chain' : 'none');
    my $real    = $pos ? $pos->{realized_pnl} : undef;
    my $day_pnl = $summary ? $summary->{day_pnl} : undef;

    my $strat_status  = $strat ? $strat->{status}        : 'UNKNOWN';
    my $dropped_ticks = $strat ? ($strat->{dropped_ticks} // 0) : 0;

    # IST timestamps
    my $now_ist = ist_time($now);
    my $bar_ist = bar_utc_to_ist($st_bar);

    # ── Gather per-leg data ───────────────────────────────────────────────
    # All SELL legs (open) and BUY legs (closes), paired by security_id + time
    my @sell_legs = sort { ($a->{id}//0) <=> ($b->{id}//0) }
                    grep { ($_->{side}//'') eq 'SELL' && ($_->{exchange_segment}//'') eq 'NSE_FNO' } @orders;
    my @buy_legs  = sort { ($a->{id}//0) <=> ($b->{id}//0) }
                    grep { ($_->{side}//'') eq 'BUY'  && ($_->{exchange_segment}//'') eq 'NSE_FNO' } @orders;

    # Compute per-leg valid P&L (skip bad ltp=0 fills)
    my $valid_open_pnl  = 0;
    my $valid_open_qty  = 0;
    my $valid_closed_pnl = 0;
    for my $o (@sell_legs) {
        my $fp_leg = $fill_px{ $o->{id} } // 0;
        next unless $fp_leg > 0;
        $valid_open_qty += $o->{qty} // 0;
        $valid_open_pnl += ($fp_leg - $ltp_for_pnl) * ($o->{qty} // 0) if $ltp_for_pnl;
    }

    # ── Render ────────────────────────────────────────────────────────────
    cls();
    my $W    = 90;
    my $SEP  = grey('  ' . ('─' x $W));
    my $DSEP = '  ' . ('═' x $W);

    # ── Header bar ───────────────────────────────────────────────────────
    print cyan($DSEP), "\n";
    printf "  %s   %s IST   NIFTY %s   ST(%s) %s  val:%-10s  bar:%s\n",
        bold('PDP Monitor'), cyan($now_ist),
        cyan(fp($nifty_ltp)),
        $TF, fdir($st_dir), fp($st_val), $bar_ist;
    print cyan($DSEP), "\n";

    if ($st_flipped || $flip_alert) {
        printf "  %s\n", yel('⚡ SuperTrend FLIP — strategy closing current leg and re-entering opposite side');
    }

    # ── Per-strategy group ────────────────────────────────────────────────
    # Build a list of all loaded strategies; render each as its own block.
    my @all_strats = @{ $strats // [] };
    push @all_strats, { id => 'supertrend_short', status => 'UNKNOWN' } unless @all_strats;

    my $blotter_hdr = sub {
        printf "  %-3s  %-22s  %-9s  %-13s  %-8s  %-8s  %-9s  %-10s  %-13s  %-8s  %-14s  %s\n",
            grey('#'), grey('Instrument'), grey('Lots'),
            grey('Entry IST'), grey('Entry ₹'), grey('Curr ₹'), grey('Diff/unit'),
            grey('Open P&L'), grey('Close IST'), grey('Close ₹'), grey('Real P&L'),
            grey('Stop Dist');
    };

    for my $s (@all_strats) {
        my $sid      = $s->{id} // 'unknown';
        my $sstatus  = $s->{status} // 'UNKNOWN';
        my $sdropped = $s->{dropped_ticks} // 0;

        # Risk-stop params: prefer strategy API params, fall back to defaults
        my $params       = ref($s->{params}) eq 'HASH' ? $s->{params} : {};
        my $leg_stop_per_lot = looks_like_number($params->{leg_stop_per_lot})
            ? $params->{leg_stop_per_lot} + 0 : $LEG_STOP_PER_LOT_DEFAULT;
        my $day_stop = looks_like_number($params->{day_stop})
            ? $params->{day_stop} + 0 : $DAY_STOP_DEFAULT;

        # Strategy group header
        my $status_badge = $sstatus eq 'RUNNING' ? green("[$sstatus]") : red("[$sstatus]");
        printf "\n  %s %s  %s  dropped:%s\n",
            bold("▶ $sid"), $status_badge,
            grey("NIFTY ${\(uc $exp_type)} ${\($exp_strike||'--')}  expiry:$CHAIN_EXPIRY"
                 . "  leg_stop:${leg_stop_per_lot}/lot  day_cap:${day_stop}"),
            $sdropped;
        print $SEP, "\n";

        # Filter orders for this strategy
        my @s_sell = sort { ($a->{id}//0) <=> ($b->{id}//0) }
                     grep { ($_->{side}//'') eq 'SELL'
                          && ($_->{status}//'') eq 'FILLED'
                          && ($_->{exchange_segment}//'') eq 'NSE_FNO'
                          && ($_->{strategy_id}//'') eq $sid } @orders;
        my @s_buy  = sort { ($a->{id}//0) <=> ($b->{id}//0) }
                     grep { ($_->{side}//'') eq 'BUY'
                          && ($_->{status}//'') eq 'FILLED'
                          && ($_->{exchange_segment}//'') eq 'NSE_FNO'
                          && ($_->{strategy_id}//'') eq $sid } @orders;

        if (!@s_sell) {
            printf "  %s\n", grey('  Waiting for first bar close...');
            print $SEP, "\n";
            next;
        }

        $blotter_hdr->();
        print $SEP, "\n";

        my ($tot_open_pnl, $tot_real_pnl) = (0, 0);

        for my $o (@s_sell) {
            my $oid      = $o->{id} // '?';
            my $leg_qty  = $o->{qty} // 0;
            my $leg_lots = int($leg_qty / 65 + 0.5);
            my $entry_px = $fill_px{$oid} // 0;
            my $entry_ts = utc_to_ist($o->{filled_at});
            my $bad_fill = ($entry_px <= 0) ? 1 : 0;

            # Match earliest BUY after this SELL for same security_id + strategy
            my ($close_o) = grep {
                ($_->{security_id}//'') eq ($o->{security_id}//'')
                && defined($_->{placed_at}) && defined($o->{placed_at})
                && ($_->{placed_at}//'') gt ($o->{placed_at}//'')
            } @s_buy;
            my $close_px = $close_o ? ($fill_px{$close_o->{id}} // 0) : 0;
            my $close_ts = $close_o ? utc_to_ist($close_o->{filled_at}) : grey('  open  ');

            my ($open_pnl_str, $real_pnl_str);
            if ($close_o && $close_px > 0) {
                my $real = ($entry_px - $close_px) * $leg_qty;
                $tot_real_pnl += $real unless $bad_fill;
                $real_pnl_str  = fpnl($bad_fill ? undef : $real);
                $open_pnl_str  = grey(' closed  ');
            } elsif ($bad_fill) {
                $open_pnl_str = red(' bad fill');
                $real_pnl_str = grey('  --  ');
            } else {
                my $opnl = $ltp_for_pnl ? ($entry_px - $ltp_for_pnl) * $leg_qty : undef;
                $tot_open_pnl += $opnl // 0;
                $open_pnl_str  = fpnl($opnl);
                $real_pnl_str  = grey('  open  ');
            }

            my $diff = (!$bad_fill && $ltp_for_pnl && !$close_o) ? $entry_px - $ltp_for_pnl : undef;
            my $diff_str  = defined($diff)
                ? ($diff >= 0 ? green(sprintf('%+7.2f', $diff)) : red(sprintf('%+7.2f', $diff)))
                : grey('    --  ');
            my $entry_col = $bad_fill
                ? red(sprintf('%7.2f!', $entry_px))
                : sprintf('%8.2f', $entry_px);
            my $curr_col  = $ltp_for_pnl ? sprintf('%8.2f', $ltp_for_pnl) : grey('    --  ');
            my $exp_lbl   = expiry_label($CHAIN_EXPIRY);
            my $instr     = sprintf('NIFTY%s%s %s', $exp_strike||'????', uc($exp_type), $exp_lbl);

            # Per-leg stop distance (open legs only).
            # Use aggregate position lots ($lots from $pos) so the distance matches
            # what the strategy actually monitors, not the individual order's lot count.
            my $stop_str = grey('    --    ');
            if (!$close_o && !$bad_fill && $ltp_for_pnl > 0 && $entry_px > 0 && $lots > 0) {
                my $pos_qty = $lots * 65;
                my $mtm    = ($entry_px - $ltp_for_pnl) * $pos_qty;   # +ve = profit
                my $slimit = $leg_stop_per_lot * $lots;                 # stop budget (aggregate)
                my $dist   = $mtm + $slimit;    # ₹ room before stop fires
                if ($dist <= 0) {
                    $stop_str = red(sprintf('STOP! %+.0f', $dist));
                } elsif ($dist < $STOP_ALERT_FRAC * $slimit) {
                    $stop_str = yel(sprintf('near  %+.0f', $dist));
                } else {
                    $stop_str = grey(sprintf('ok   %+.0f', $dist));
                }
            }

            printf "  %-3s  %-22s  %dL/%3dq  %-13s  %-8s  %-8s  %s  %s  %-13s  %-8s  %-14s  %s\n",
                $oid, $instr, $leg_lots, $leg_qty,
                $entry_ts, $entry_col, $curr_col, $diff_str,
                $open_pnl_str, $close_ts,
                $close_px > 0 ? sprintf('%8.2f', $close_px) : grey('    --  '),
                $real_pnl_str, $stop_str;
        }

        # Strategy totals
        my $tot_pnl = $tot_open_pnl + $tot_real_pnl;
        print $SEP, "\n";
        printf "  %-28s  open P&L: %s   realized: %s   %s\n",
            grey(sprintf('%d lots open  ltp:[%s]', $lots, $ltp_src)),
            fpnl($tot_open_pnl), fpnl($tot_real_pnl),
            bold(sprintf('TOTAL: %s', $tot_pnl >= 0
                ? green(sprintf('%+.2f', $tot_pnl))
                : red(sprintf('%+.2f', $tot_pnl))));

        # Greeks + day realized vs day cap
        my $day_cap_str = do {
            my $pct = ($day_stop > 0 && defined $tot_real_pnl)
                ? abs($tot_real_pnl) / $day_stop * 100 : 0;
            my $used = fpnl($tot_real_pnl);
            my $cap  = sprintf('cap:-%s', fp($day_stop, '%.0f'));
            $pct >= 80 ? red("realized:$used $cap  [!!!]")
                       : $pct >= 50 ? yel("realized:$used $cap")
                       :              grey("realized:$used $cap");
        };
        printf "  Δ:%-7s  Γ:%-8s  Θ:%-9s  ν:%-7s  IV:%s%%   %s\n",
            fg($g_delta,'%+.4f'), fg($g_gamma,'%.5f'),
            fg($g_theta,'%+.2f'), fg($g_vega,'%.4f'),
            defined($g_iv) ? sprintf('%.2f',$g_iv) : '--',
            $day_cap_str;
        print $SEP, "\n";
    }

    print cyan($DSEP), "\n";
    print grey('  Ctrl+C to exit'), "\n";

    my $elapsed = time() - $t0;
    my $wait    = $POLL_SEC - $elapsed;
    sleep($wait) if $wait > 0;
}
