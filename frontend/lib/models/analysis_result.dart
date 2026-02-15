/// 分析结果数据模型
class AnalysisResult {
  final double sentimentScore;
  final String sentimentLabel;
  final List<Opinion> opinions;
  final String summary;
  final double heatScore;
  final DateTime createdAt;

  AnalysisResult({
    required this.sentimentScore,
    required this.sentimentLabel,
    required this.opinions,
    required this.summary,
    required this.heatScore,
    required this.createdAt,
  });

  factory AnalysisResult.fromJson(Map<String, dynamic> json) {
    return AnalysisResult(
      sentimentScore: (json['sentiment_score'] as num).toDouble(),
      sentimentLabel: json['sentiment_label'] as String,
      opinions: (json['opinions'] as List)
          .map((e) => Opinion.fromJson(e as Map<String, dynamic>))
          .toList(),
      summary: json['summary'] as String,
      heatScore: (json['heat_score'] as num).toDouble(),
      createdAt: DateTime.parse(json['created_at'] as String),
    );
  }
}

/// 观点数据模型
class Opinion {
  final String description;
  final double supportRate;

  Opinion({required this.description, required this.supportRate});

  factory Opinion.fromJson(Map<String, dynamic> json) {
    return Opinion(
      description: json['description'] as String,
      supportRate: (json['support_rate'] as num).toDouble(),
    );
  }
}
