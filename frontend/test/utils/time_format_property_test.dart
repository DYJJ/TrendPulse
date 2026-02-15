import 'dart:math';
import 'package:flutter_test/flutter_test.dart';
import 'package:trendpulse/utils/time_format.dart';

/// Property 6: 相对时间格式化正确性
///
/// **Validates: Requirements 4.4**
///
/// 对于任意有效的 DateTime 时间戳，formatRelativeTime 应返回
/// 正确反映该时间戳与当前时间差值的人类可读字符串。
void main() {
  group('Feature: data-page-enhancement, Property 6: 相对时间格式化正确性', () {
    /// 生成随机的秒数差值（0 到 365*24*3600 之间）
    int _randomDiffSeconds(Random rng) {
      // 覆盖从 0 秒到约 1 年的范围
      return rng.nextInt(365 * 24 * 3600);
    }

    test('随机时间差的格式化结果与时间区间一致（100 次迭代）', () {
      final rng = Random(42);
      final now = DateTime(2026, 2, 14, 12, 0, 0);

      for (var i = 0; i < 100; i++) {
        final diffSeconds = _randomDiffSeconds(rng);
        final timestamp = now.subtract(Duration(seconds: diffSeconds));
        final result = formatRelativeTime(timestamp, now: now);

        final diffMinutes = diffSeconds ~/ 60;
        final diffHours = diffSeconds ~/ 3600;
        final diffDays = diffSeconds ~/ 86400;

        if (diffSeconds < 60) {
          expect(result, equals('刚刚'),
              reason: '迭代 $i: ${diffSeconds}秒差应返回"刚刚"');
        } else if (diffMinutes < 60) {
          expect(result, equals('$diffMinutes分钟前'),
              reason: '迭代 $i: ${diffMinutes}分钟差应返回"$diffMinutes分钟前"');
        } else if (diffHours < 24) {
          expect(result, equals('$diffHours小时前'),
              reason: '迭代 $i: ${diffHours}小时差应返回"$diffHours小时前"');
        } else if (diffDays < 30) {
          expect(result, equals('$diffDays天前'),
              reason: '迭代 $i: ${diffDays}天差应返回"$diffDays天前"');
        } else {
          final months = diffDays ~/ 30;
          expect(result, equals('$months个月前'),
              reason: '迭代 $i: ${diffDays}天差应返回"$months个月前"');
        }
      }
    });

    test('未来时间戳始终返回"刚刚"（100 次迭代）', () {
      final rng = Random(99);
      final now = DateTime(2026, 2, 14, 12, 0, 0);

      for (var i = 0; i < 100; i++) {
        // 生成 1 秒到 1 天后的未来时间
        final futureSeconds = rng.nextInt(86400) + 1;
        final futureTimestamp = now.add(Duration(seconds: futureSeconds));
        final result = formatRelativeTime(futureTimestamp, now: now);

        expect(result, equals('刚刚'),
            reason: '迭代 $i: 未来时间戳(+${futureSeconds}s)应返回"刚刚"');
      }
    });
  });
}
