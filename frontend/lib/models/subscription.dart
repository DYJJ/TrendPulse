/// 订阅数据模型
class Subscription {
  final String subscriptionId;
  final String keyword;
  final String language;
  final List<String> sources;
  final int intervalHours;
  final int limitPerSource;
  final int alertThreshold;
  final String status;
  final DateTime createdAt;

  Subscription({
    required this.subscriptionId,
    required this.keyword,
    required this.language,
    required this.sources,
    required this.intervalHours,
    required this.limitPerSource,
    required this.alertThreshold,
    required this.status,
    required this.createdAt,
  });

  factory Subscription.fromJson(Map<String, dynamic> json) {
    return Subscription(
      subscriptionId: json['subscription_id'] as String,
      keyword: json['keyword'] as String,
      language: json['language'] as String,
      sources: List<String>.from(json['sources'] as List),
      intervalHours: json['interval_hours'] as int,
      limitPerSource: json['limit_per_source'] as int? ?? 50,
      alertThreshold: json['alert_threshold'] as int,
      status: json['status'] as String,
      createdAt: DateTime.parse(json['created_at'] as String),
    );
  }
}
