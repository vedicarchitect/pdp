/// A background job record from `GET /api/v1/jobs/{id}`.
class JobRecord {
  const JobRecord({
    required this.id,
    required this.type,
    required this.status,
    required this.progress,
    this.progressMessage,
    this.result,
    this.error,
  });

  final String id;
  final String type;
  final String status; // PENDING | RUNNING | COMPLETED | FAILED | CANCELLED
  final int progress;
  final String? progressMessage;
  final Map<String, dynamic>? result;
  final String? error;

  bool get isTerminal => status == 'COMPLETED' || status == 'FAILED' || status == 'CANCELLED';

  factory JobRecord.fromJson(Map<String, dynamic> json) {
    return JobRecord(
      id: json['id'] as String,
      type: json['type'] as String? ?? '',
      status: json['status'] as String? ?? 'PENDING',
      progress: (json['progress'] as num?)?.toInt() ?? 0,
      progressMessage: json['progress_message'] as String?,
      result: json['result'] as Map<String, dynamic>?,
      error: json['error'] as String?,
    );
  }
}

/// One `/ws/jobs/{id}` progress frame: `{progress, message}`. `message` is one
/// of "Completed", "Cancelled", "Failed: <reason>", or a task-specific status
/// string while running.
class JobProgress {
  const JobProgress({required this.progress, required this.message});

  final int progress;
  final String message;

  bool get isCompleted => message == 'Completed';
  bool get isCancelled => message == 'Cancelled';
  bool get isFailed => message.startsWith('Failed:');
  bool get isTerminal => isCompleted || isCancelled || isFailed;

  factory JobProgress.fromJson(Map<String, dynamic> json) {
    return JobProgress(
      progress: (json['progress'] as num?)?.toInt() ?? 0,
      message: json['message'] as String? ?? '',
    );
  }
}
