/// 采集任务数据模型
class CollectionTask {
  final String taskId;
  final String status;
  final DateTime createdAt;

  CollectionTask({
    required this.taskId,
    required this.status,
    required this.createdAt,
  });

  factory CollectionTask.fromJson(Map<String, dynamic> json) {
    return CollectionTask(
      taskId: json['task_id'] as String,
      status: json['status'] as String,
      createdAt: DateTime.parse(json['created_at'] as String),
    );
  }
}

/// 采集任务状态
class CollectionStatus {
  final String taskId;
  final String status;
  final int progress;
  final String? error;
  final DateTime createdAt;
  final DateTime updatedAt;

  CollectionStatus({
    required this.taskId,
    required this.status,
    required this.progress,
    this.error,
    required this.createdAt,
    required this.updatedAt,
  });

  factory CollectionStatus.fromJson(Map<String, dynamic> json) {
    return CollectionStatus(
      taskId: json['task_id'] as String,
      status: json['status'] as String,
      progress: json['progress'] as int,
      error: json['error'] as String?,
      createdAt: DateTime.parse(json['created_at'] as String),
      updatedAt: DateTime.parse(json['updated_at'] as String),
    );
  }
}
