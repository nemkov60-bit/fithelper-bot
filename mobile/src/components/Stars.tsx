import { Pressable, View } from 'react-native';
import Svg, { Path } from 'react-native-svg';

import { colors } from '../lib/theme';

const STAR = 'M12 3l2.7 5.6 6.1.9-4.4 4.3 1 6.1L12 17l-5.4 2.9 1-6.1-4.4-4.3 6.1-.9z';

// Звёзды рейтинга: показ (value) или выбор (onChange).
export function Stars({ value, size = 18, onChange }: { value: number; size?: number; onChange?: (v: number) => void }) {
  return (
    <View style={{ flexDirection: 'row', gap: onChange ? 8 : 2 }} accessible={!onChange} accessibilityLabel={`Оценка ${value} из 5`}>
      {[1, 2, 3, 4, 5].map((n) => {
        const filled = value >= n - 0.25;
        const star = (
          <Svg width={size} height={size} viewBox="0 0 24 24">
            <Path d={STAR} fill={filled ? colors.accent : 'none'} stroke={filled ? colors.accent : colors.borderStrong} strokeWidth={1.8} strokeLinejoin="round" />
          </Svg>
        );
        return onChange ? (
          <Pressable key={n} accessibilityRole="button" accessibilityLabel={`${n} из 5`} onPress={() => onChange(n)} hitSlop={6}>{star}</Pressable>
        ) : <View key={n}>{star}</View>;
      })}
    </View>
  );
}
