import type { ReactNode } from 'react';
import {
  ActivityIndicator, Pressable, RefreshControl, ScrollView, StyleSheet, Text, View,
  type StyleProp, type TextStyle, type ViewStyle,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import Svg, { Circle } from 'react-native-svg';

import { colors, fonts, radius } from '../lib/theme';
import { Icon, type IconName } from './Icon';

// ---------- Текст ----------

type TextVariant = 'h1' | 'h2' | 'h3' | 'body' | 'label' | 'small' | 'big';

// Функция, а не константа: цвет берётся из текущей темы.
const textStyles = (): Record<TextVariant, TextStyle> => ({
  big: { fontFamily: fonts.heading, fontSize: 30, letterSpacing: fonts.headingSpacing - 0.2, color: colors.text },
  h1: { fontFamily: fonts.heading, fontSize: 28, letterSpacing: fonts.headingSpacing, color: colors.text },
  h2: { fontFamily: fonts.title, fontSize: 20, letterSpacing: fonts.headingSpacing / 2, color: colors.text },
  h3: { fontFamily: fonts.title, fontSize: 16, color: colors.text },
  body: { fontFamily: fonts.semibold, fontSize: 15, color: colors.text, lineHeight: 21 },
  label: { fontFamily: fonts.bold, fontSize: 12, letterSpacing: 0.6, color: colors.muted },
  small: { fontFamily: fonts.semibold, fontSize: 13, color: colors.muted, lineHeight: 18 },
});

export function T({ v = 'body', style, children, numberOfLines }: {
  v?: TextVariant; style?: StyleProp<TextStyle>; children: ReactNode; numberOfLines?: number;
}) {
  return <Text style={[textStyles()[v], style]} numberOfLines={numberOfLines}>{children}</Text>;
}

// ---------- Экран ----------

export function Screen({ children, refreshing, onRefresh, bottomInset = 120, scroll = true }: {
  children: ReactNode; refreshing?: boolean; onRefresh?: () => void; bottomInset?: number; scroll?: boolean;
}) {
  return (
    <SafeAreaView style={{ flex: 1, backgroundColor: colors.bg }} edges={['top']}>
      {scroll ? (
        <ScrollView
          contentContainerStyle={{ padding: 20, paddingBottom: bottomInset, gap: 14 }}
          showsVerticalScrollIndicator={false}
          refreshControl={onRefresh ? (
            <RefreshControl refreshing={!!refreshing} onRefresh={onRefresh} tintColor={colors.accent} />
          ) : undefined}
        >
          {children}
        </ScrollView>
      ) : (
        <View style={{ flex: 1, padding: 20, gap: 14 }}>{children}</View>
      )}
    </SafeAreaView>
  );
}

export function Loading() {
  return (
    <View style={{ flex: 1, alignItems: 'center', justifyContent: 'center', backgroundColor: colors.bg }}>
      <ActivityIndicator color={colors.accent} size="large" />
    </View>
  );
}

export function ErrorBox({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <Card style={{ gap: 12 }}>
      <T>{message}</T>
      {onRetry ? <Button title="Повторить" variant="secondary" onPress={onRetry} /> : null}
    </Card>
  );
}

// ---------- Блоки ----------

export function Card({ children, style, accent }: { children: ReactNode; style?: StyleProp<ViewStyle>; accent?: boolean }) {
  return <View style={[accent ? s.cardAccent : s.card, style]}>{children}</View>;
}

export function Button({ title, onPress, variant = 'primary', icon, disabled, loading, style, small }: {
  title: string; onPress?: () => void; variant?: 'primary' | 'secondary' | 'ghost' | 'dark';
  icon?: IconName; disabled?: boolean; loading?: boolean; style?: StyleProp<ViewStyle>; small?: boolean;
}) {
  const bg = variant === 'primary' ? colors.accent : variant === 'secondary' ? colors.surface2 : variant === 'dark' ? colors.bg : 'transparent';
  const fg = variant === 'primary' ? colors.onAccent : colors.text;
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={title}
      disabled={disabled || loading}
      onPress={onPress}
      style={({ pressed }) => [
        s.button,
        { backgroundColor: bg, height: small ? 44 : 58, opacity: disabled ? 0.45 : pressed ? 0.85 : 1 },
        variant === 'ghost' ? { borderWidth: 1, borderColor: colors.borderStrong } : null,
        style,
      ]}
    >
      {loading ? <ActivityIndicator color={fg} /> : (
        <>
          <Text style={{ fontFamily: fonts.extrabold, fontSize: small ? 14 : 17, color: fg }}>{title}</Text>
          {icon ? <Icon name={icon} size={20} color={fg} strokeWidth={2.4} /> : null}
        </>
      )}
    </Pressable>
  );
}

export function Segmented<K extends string>({ options, value, onChange, label }: {
  options: { key: K; label: string }[]; value: K; onChange: (k: K) => void; label: string;
}) {
  return (
    <View accessibilityRole="radiogroup" accessibilityLabel={label} style={s.segmented}>
      {options.map((o) => {
        const on = o.key === value;
        return (
          <Pressable
            key={o.key}
            accessibilityRole="radio"
            accessibilityState={{ selected: on }}
            onPress={() => onChange(o.key)}
            style={[s.segment, on ? { backgroundColor: colors.accent } : null]}
          >
            <Text style={{ fontFamily: on ? fonts.extrabold : fonts.bold, fontSize: 14, color: on ? colors.onAccent : colors.soft }}>
              {o.label}
            </Text>
          </Pressable>
        );
      })}
    </View>
  );
}

export function Chip({ label, on, onPress, style }: { label: string; on?: boolean; onPress?: () => void; style?: StyleProp<ViewStyle> }) {
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityState={{ selected: !!on }}
      onPress={onPress}
      style={[s.chip, { backgroundColor: on ? colors.accent : colors.surface2 }, style]}
    >
      <Text style={{ fontFamily: fonts.extrabold, fontSize: 16, color: on ? colors.onAccent : colors.text }}>{label}</Text>
    </Pressable>
  );
}

export function Badge({ label, tone = 'accent' }: { label: string; tone?: 'accent' | 'dark' | 'outline' | 'orange' }) {
  const style: ViewStyle =
    tone === 'accent' ? { backgroundColor: colors.accent } :
    tone === 'orange' ? { backgroundColor: colors.orange } :
    tone === 'outline' ? { borderWidth: 1, borderColor: colors.accent } : { backgroundColor: colors.surface2 };
  const color = tone === 'accent' || tone === 'orange' ? colors.onAccent : tone === 'outline' ? colors.accent : colors.accent;
  return (
    <View style={[s.badge, style]}>
      <Text style={{ fontFamily: fonts.extrabold, fontSize: 12, color }}>{label}</Text>
    </View>
  );
}

export function ProgressBar({ value, color = colors.accent, height = 6 }: { value: number; color?: string; height?: number }) {
  const pct = Math.max(0, Math.min(1, value)) * 100;
  return (
    <View style={{ height, borderRadius: height / 2, backgroundColor: colors.border, overflow: 'hidden' }}>
      <View style={{ width: `${pct}%`, height, backgroundColor: color }} />
    </View>
  );
}

export function Ring({ value, size = 54, stroke = 7, label }: { value: number; size?: number; stroke?: number; label: string }) {
  const r = (size - stroke) / 2;
  const c = 2 * Math.PI * r;
  const v = Math.max(0, Math.min(1, value));
  return (
    <View accessible accessibilityLabel={label}>
      <Svg width={size} height={size}>
        <Circle cx={size / 2} cy={size / 2} r={r} stroke={colors.border} strokeWidth={stroke} fill="none" />
        <Circle cx={size / 2} cy={size / 2} r={r} stroke={colors.accent} strokeWidth={stroke} fill="none"
          strokeLinecap="round" strokeDasharray={`${c * v} ${c}`} transform={`rotate(-90 ${size / 2} ${size / 2})`} />
      </Svg>
    </View>
  );
}

export function Stat({ value, label }: { value: string; label: string }) {
  return (
    <Card style={{ flex: 1, padding: 14, gap: 4 }}>
      <T v="h2" style={{ fontSize: 22 }}>{value}</T>
      <T v="small" style={{ fontSize: 12 }}>{label}</T>
    </Card>
  );
}

export function IconButton({ icon, label, onPress, style }: { icon: IconName; label: string; onPress?: () => void; style?: StyleProp<ViewStyle> }) {
  return (
    <Pressable accessibilityRole="button" accessibilityLabel={label} onPress={onPress} style={[s.iconButton, style]}>
      <Icon name={icon} size={20} color={colors.text} strokeWidth={2.2} />
    </Pressable>
  );
}

// Стили, зависящие от цветов, — геттеры: читают текущую тему в момент отрисовки.
const shadow = () => (colors.light ? { shadowColor: colors.accent, shadowOpacity: 0.14, shadowRadius: 18, shadowOffset: { width: 0, height: 8 }, elevation: 3 } : {});
export const s = {
  get card() { return { backgroundColor: colors.surface, borderColor: colors.border, borderWidth: 1, borderRadius: radius.lg, padding: 16, ...shadow() }; },
  get cardAccent() { return { backgroundColor: colors.accent, borderRadius: radius.lg, padding: 16, ...shadow() }; },
  button: { borderRadius: radius.pill, flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 10, paddingHorizontal: 18 } as const,
  get segmented() { return { flexDirection: 'row', gap: 6, padding: 5, borderRadius: radius.pill, backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border } as const; },
  segment: { flex: 1, height: 44, borderRadius: radius.pill, alignItems: 'center', justifyContent: 'center' } as const,
  chip: { flex: 1, minWidth: 48, height: 48, borderRadius: 16, alignItems: 'center', justifyContent: 'center' } as const,
  badge: { alignSelf: 'flex-start', paddingHorizontal: 10, paddingVertical: 5, borderRadius: radius.pill } as const,
  get iconButton() { return { width: 46, height: 46, borderRadius: 23, backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border, alignItems: 'center', justifyContent: 'center' } as const; },
  row: { flexDirection: 'row', alignItems: 'center', gap: 12 } as const,
};
