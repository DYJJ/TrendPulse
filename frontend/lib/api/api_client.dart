import 'package:dio/dio.dart';
import 'package:trendpulse/config.dart';
import 'package:trendpulse/models/analysis_result.dart';
import 'package:trendpulse/models/collection_task.dart';
import 'package:trendpulse/models/post.dart';
import 'package:trendpulse/models/subscription.dart';

/// API客户端
///
/// 封装所有与后端API的HTTP通信，包括采集任务、分析结果、
/// 帖子列表、订阅管理和思维导图接口。
class ApiClient {
  late final Dio _dio;

  ApiClient({String? baseUrl}) {
    _dio = Dio(BaseOptions(
      baseUrl: baseUrl ?? AppConfig.apiBaseUrl,
      connectTimeout: Duration(milliseconds: AppConfig.connectTimeout),
      receiveTimeout: Duration(milliseconds: AppConfig.receiveTimeout),
      headers: {'Content-Type': 'application/json'},
    ));

    // 添加错误拦截器
    _dio.interceptors.add(InterceptorsWrapper(
      onError: (error, handler) {
        final message = _extractErrorMessage(error);
        handler.reject(DioException(
          requestOptions: error.requestOptions,
          error: message,
          type: error.type,
          response: error.response,
        ));
      },
    ));
  }

  /// 从错误响应中提取可读的错误信息
  String _extractErrorMessage(DioException error) {
    if (error.response?.data is Map) {
      final data = error.response!.data as Map;
      return data['detail']?.toString() ?? data['error']?.toString() ?? '请求失败';
    }
    if (error.type == DioExceptionType.connectionTimeout) {
      return '连接超时，请检查网络';
    }
    if (error.type == DioExceptionType.receiveTimeout) {
      return '响应超时，请稍后重试';
    }
    return error.message ?? '未知错误';
  }

  // ===== 采集任务 =====

  /// 创建采集任务
  Future<CollectionTask> createCollection({
    required String keyword,
    required String language,
    required int limit,
    required List<String> sources,
  }) async {
    final response = await _dio.post('/collections', data: {
      'keyword': keyword,
      'language': language,
      'limit': limit,
      'sources': sources,
    });
    return CollectionTask.fromJson(response.data);
  }

  /// 查询采集任务状态
  Future<CollectionStatus> getCollectionStatus(String taskId) async {
    final response = await _dio.get('/collections/$taskId');
    return CollectionStatus.fromJson(response.data);
  }

  // ===== 分析结果 =====

  /// 获取分析结果
  Future<AnalysisResult> getAnalysis(String taskId) async {
    final response = await _dio.get('/analysis/$taskId');
    return AnalysisResult.fromJson(response.data);
  }

  // ===== 帖子列表 =====

  /// 获取帖子列表（分页 + 筛选 + 排序 + 搜索）
  Future<PostListResponse> getPosts(
    String taskId, {
    int page = 1,
    int pageSize = 20,
    String? source,
    String? sortBy,
    String sortOrder = 'desc',
    String? search,
  }) async {
    final queryParameters = <String, dynamic>{
      'page': page,
      'page_size': pageSize,
    };
    // 将非空参数添加到查询参数中
    if (source != null) queryParameters['source'] = source;
    if (sortBy != null) queryParameters['sort_by'] = sortBy;
    queryParameters['sort_order'] = sortOrder;
    if (search != null) queryParameters['search'] = search;

    final response = await _dio.get('/posts/$taskId', queryParameters: queryParameters);
    return PostListResponse.fromJson(response.data);
  }

  // ===== 订阅管理 =====

  /// 创建订阅
  Future<Subscription> createSubscription({
    required String keyword,
    String language = 'en',
    List<String> sources = const ['reddit', 'youtube', 'twitter'],
    int intervalHours = 6,
    int limitPerSource = 50,
    int alertThreshold = 30,
  }) async {
    final response = await _dio.post('/subscriptions', data: {
      'keyword': keyword,
      'language': language,
      'sources': sources,
      'interval_hours': intervalHours,
      'limit_per_source': limitPerSource,
      'alert_threshold': alertThreshold,
    });
    return Subscription.fromJson(response.data);
  }

  /// 获取订阅列表
  Future<List<Subscription>> getSubscriptions() async {
    final response = await _dio.get('/subscriptions');
    return (response.data as List)
        .map((e) => Subscription.fromJson(e as Map<String, dynamic>))
        .toList();
  }

  /// 取消订阅
  Future<void> cancelSubscription(String subscriptionId) async {
    await _dio.delete('/subscriptions/$subscriptionId');
  }

  // ===== 思维导图 =====

  /// 获取思维导图Mermaid代码
  Future<String> getMindmap(String taskId) async {
    final response = await _dio.get('/mindmap/$taskId');
    return response.data['mermaid_code'] as String;
  }
}
