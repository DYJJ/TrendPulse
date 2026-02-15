/// 应用配置常量
class AppConfig {
  /// 后端API基础地址
  static const String apiBaseUrl = 'http://localhost:8000/api/v1';

  /// 请求超时时间（毫秒）
  static const int connectTimeout = 10000;
  static const int receiveTimeout = 30000;

  /// 分页默认参数
  static const int defaultPageSize = 20;

  /// 情感分数颜色阈值
  static const int negativeBound = 30;
  static const int positiveBound = 70;

  AppConfig._();
}
