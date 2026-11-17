import { Image, View } from 'react-native';

import { photoUrl } from '../lib/api';
import { colors, fonts } from '../lib/theme';
import { T } from './ui';

// Фото тренера или его инициалы.
export function TrainerAvatar({ name, url, size = 56 }: { name: string; url: string | null | undefined; size?: number }) {
  if (url) {
    return <Image source={{ uri: photoUrl(url) }} accessibilityLabel={`Фото: ${name}`}
      style={{ width: size, height: size, borderRadius: size / 2, backgroundColor: colors.surface2 }} />;
  }
  const initials = name.split(' ').map((w) => w[0]).join('').slice(0, 2).toUpperCase();
  return (
    <View style={{ width: size, height: size, borderRadius: size / 2, backgroundColor: colors.accent, alignItems: 'center', justifyContent: 'center' }}>
      <T style={{ color: colors.onAccent, fontFamily: fonts.extrabold, fontSize: size / 3 }}>{initials}</T>
    </View>
  );
}
