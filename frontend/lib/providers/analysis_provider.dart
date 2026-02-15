import 'package:flutter/foundation.dart';
import 'package:trendpulse/api/api_client.dart';
import 'package:trendpulse/models/analysis_result.dart';

/// 分析结果状态管理
///
/// 管理采集任务的创建、状态轮询和分析结果获取。
class AnalysisProvider extends ChangeNotifier {
  final ApiClient _apiClient;

  // 当前任务信息
  String? _taskId;
  String _taskStatus = '';
  int _progress = 0;
  AnalysisResult? _result;
  String? _mermaidCode;

  // 加载状态
  bool _isLoading = false;
  bool _isMindmapLoading = false;
  String? _error;

  AnalysisProvider(this._apiClient);

  // 只读访问器
  String? get taskId => _taskId;
  String get taskStatus => _taskStatus;
  int get progress => _progress;
  AnalysisResult? get result => _result;
  String? get mermaidCode => _mermaidCode;
  bool get isLoading => _isLoading;
  bool get isMindmapLoading => _isMindmapLoading;
  String? get error => _error;

  /// 创建采集任务并开始轮询状态
  Future<void> createCollection({
    required String keyword,
    required String language,
    required int limit,
    required List<String> sources,
  }) async {
    _isLoading = true;
    _error = null;
    _result = null;
    _mermaidCode = null;
    notifyListeners();

    try {
      final task = await _apiClient.createCollection(
        keyword: keyword,
        language: language,
        limit: limit,
        sources: sources,
      );
      _taskId = task.taskId;
      _taskStatus = task.status;
      notifyListeners();

      // 轮询任务状态直到完成或失败
      await _pollTaskStatus();
    } catch (e) {
      _error = e.toString();
    } finally {
      _isLoading = false;
      notifyListeners();
    }
  }

  /// 轮询任务状态
  Future<void> _pollTaskStatus() async {
    if (_taskId == null) return;

    while (true) {
      await Future.delayed(const Duration(seconds: 2));

      try {
        final status = await _apiClient.getCollectionStatus(_taskId!);
        _taskStatus = status.status;
        _progress = status.progress;
        notifyListeners();

        if (status.status == 'completed') {
          await _fetchAnalysisResult();
          break;
        } else if (status.status == 'failed') {
          _error = status.error ?? '任务执行失败';
          break;
        }
      } catch (e) {
        _error = e.toString();
        break;
      }
    }
  }

  /// 获取分析结果
  Future<void> _fetchAnalysisResult() async {
    if (_taskId == null) return;

    try {
      _result = await _apiClient.getAnalysis(_taskId!);
      notifyListeners();
    } catch (e) {
      _error = '获取分析结果失败: $e';
      notifyListeners();
    }
  }

  /// 加载指定任务的分析结果（用于直接查看已有任务）
  Future<void> loadAnalysis(String taskId) async {
    _isLoading = true;
    _error = null;
    _taskId = taskId;
    notifyListeners();

    try {
      _result = await _apiClient.getAnalysis(taskId);
    } catch (e) {
      _error = e.toString();
    } finally {
      _isLoading = false;
      notifyListeners();
    }
  }

  /// 获取思维导图Mermaid代码
  Future<void> loadMindmap(String taskId) async {
    _isMindmapLoading = true;
    notifyListeners();

    try {
      _mermaidCode = await _apiClient.getMindmap(taskId);
    } catch (e) {
      _error = '获取思维导图失败: $e';
    } finally {
      _isMindmapLoading = false;
      notifyListeners();
    }
  }

  /// 清除当前状态
  void clear() {
    _taskId = null;
    _taskStatus = '';
    _progress = 0;
    _result = null;
    _mermaidCode = null;
    _isMindmapLoading = false;
    _isLoading = false;
    _error = null;
    notifyListeners();
  }
}
