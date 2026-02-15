/// 相对时间格式化工具函数
///
/// 将 DateTime 转换为人类可读的相对时间字符串，
/// 如"刚刚"、"3分钟前"、"2小时前"等。
String formatRelativeTime(DateTime timestamp, {DateTime? now}) {
  final current = now ?? DateTime.now();
  final diff = current.difference(timestamp);

  if (diff.isNegative) {
    return '刚刚';
  }

  final seconds = diff.inSeconds;
  final minutes = diff.inMinutes;
  final hours = diff.inHours;
  final days = diff.inDays;

  if (seconds < 60) {
    return '刚刚';
  } else if (minutes < 60) {
    return '$minutes分钟前';
  } else if (hours < 24) {
    return '$hours小时前';
  } else if (days < 30) {
    return '$days天前';
  } else {
    final months = (days / 30).floor();
    return '$months个月前';
  }
}
