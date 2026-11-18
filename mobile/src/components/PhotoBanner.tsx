import { LinearGradient } from 'expo-linear-gradient';
import type { ReactNode } from 'react';
import { ImageBackground, View } from 'react-native';

import { photoUrl } from '../lib/api';

// Фото 16:10 с затемнением слева: люди справа, текст слева читается на любом фото.
export function PhotoBanner({ url, children, minHeight = 210, label = 'Фото' }: {
  url: string; children?: ReactNode; minHeight?: number; label?: string;
}) {
  return (
    <ImageBackground source={{ uri: photoUrl(url) }} resizeMode="cover" accessibilityLabel={label}
      style={{ borderRadius: 28, overflow: 'hidden', minHeight, backgroundColor: '#111' }}>
      <LinearGradient colors={['rgba(8,8,10,0.88)', 'rgba(8,8,10,0.55)', 'rgba(8,8,10,0)']} locations={[0, 0.5, 0.85]}
        start={{ x: 0, y: 0.5 }} end={{ x: 1, y: 0.5 }} style={{ flex: 1, padding: 18, gap: 8, justifyContent: 'flex-end' }}>
        <View style={{ maxWidth: '70%', gap: 8 }}>{children}</View>
      </LinearGradient>
    </ImageBackground>
  );
}

export const onPhoto = { text: '#FFFFFF', soft: 'rgba(255,255,255,0.8)' };
