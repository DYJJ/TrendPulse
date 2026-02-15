import 'package:flutter/foundation.dart';
import 'package:trendpulse/api/api_client.dart';
import 'package:trendpulse/models/subscription.dart';

/// 订阅状态管理
///
/// 管理关键词订阅的创建、查询和取消。
class SubscriptionProvider extends ChangeNotifier {
  final ApiClient _apiClient;

  List<Subscription> _subscriptions = [];
  bool _isLoading = false;
  String? _error;

  SubscriptionProvider(this._apiClient);

  // 只读访问器
  List<Subscription> get subscriptions => _subscriptions;
  bool get isLoading => _isLoading;
  String? get error => _error;

  /// 加载所有活跃订阅
  Future<void> loadSubscriptions() async {
    _isLoading = true;
    _error = null;
    notifyListeners();

    try {
      _subscriptions = await _apiClient.getSubscriptions();
    } catch (e) {
      _error = e.toString();
    } finally {
      _isLoading = false;
      notifyListeners();
    }
  }

  /// 创建新订阅
  Future<void> createSubscription({
    required String keyword,
    String language = 'en',
    List<String> sources = const ['reddit', 'youtube', 'twitter'],
    int intervalHours = 6,
    int alertThreshold = 30,
  }) async {
    _isLoading = true;
    _error = null;
    notifyListeners();

    try {
      final sub = await _apiClient.createSubscription(
        keyword: keyword,
        language: language,
        sources: sources,
        intervalHours: intervalHours,
        alertThreshold: alertThreshold,
      );
      _subscriptions.insert(0, sub);
    } catch (e) {
      _error = e.toString();
    } finally {
      _isLoading = false;
      notifyListeners();
    }
  }

  /// 取消订阅
  Future<void> cancelSubscription(String subscriptionId) async {
    try {
      await _apiClient.cancelSubscription(subscriptionId);
      _subscriptions.removeWhere((s) => s.subscriptionId == subscriptionId);
      notifyListeners();
    } catch (e) {
      _error = e.toString();
      notifyListeners();
    }
  }
}
