import 'dart:convert';
import 'dart:io';

import 'package:file_selector/file_selector.dart';
import 'package:flutter/material.dart';

/// Builds a CSV string from a list of row-maps, using the union of keys
/// across rows (in first-seen order) as columns.
String buildCsv(List<Map<String, dynamic>> rows) {
  if (rows.isEmpty) return '';
  final columns = <String>[];
  for (final row in rows) {
    for (final key in row.keys) {
      if (!columns.contains(key)) columns.add(key);
    }
  }
  String escape(Object? v) {
    final s = '$v';
    if (s.contains(',') || s.contains('"') || s.contains('\n')) {
      return '"${s.replaceAll('"', '""')}"';
    }
    return s;
  }

  final buffer = StringBuffer(columns.join(','));
  buffer.write('\n');
  for (final row in rows) {
    buffer.write(columns.map((c) => escape(row[c])).join(','));
    buffer.write('\n');
  }
  return buffer.toString();
}

/// Saves [content] to a user-chosen path on disk (desktop file-save dialog).
Future<void> saveToDisk({
  required String suggestedName,
  required String content,
  required String extension,
}) async {
  final location = await getSaveLocation(
    suggestedName: suggestedName,
    acceptedTypeGroups: [
      XTypeGroup(label: extension.toUpperCase(), extensions: [extension]),
    ],
  );
  if (location == null) return;
  final path = location.path.endsWith('.$extension') ? location.path : '${location.path}.$extension';
  await File(path).writeAsString(content);
}

/// A toolbar action offering CSV/JSON export of [rows] (e.g. days, trades, or
/// a sweep leaderboard) to disk.
class ExportButton extends StatelessWidget {
  const ExportButton({super.key, required this.filenamePrefix, required this.rows});

  final String filenamePrefix;
  final List<Map<String, dynamic>> rows;

  @override
  Widget build(BuildContext context) {
    return PopupMenuButton<String>(
      icon: const Icon(Icons.download),
      tooltip: 'Export',
      onSelected: (format) async {
        final content = format == 'json' ? const JsonEncoder.withIndent('  ').convert(rows) : buildCsv(rows);
        await saveToDisk(suggestedName: '$filenamePrefix.$format', content: content, extension: format);
        if (context.mounted) {
          ScaffoldMessenger.of(context)
              .showSnackBar(SnackBar(content: Text('Exported $filenamePrefix.$format')));
        }
      },
      itemBuilder: (context) => const [
        PopupMenuItem(value: 'csv', child: Text('Export as CSV')),
        PopupMenuItem(value: 'json', child: Text('Export as JSON')),
      ],
    );
  }
}
