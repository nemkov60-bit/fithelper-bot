import * as Clipboard from 'expo-clipboard';
import { Directory, File, Paths } from 'expo-file-system';
import * as Sharing from 'expo-sharing';
import { Platform, Share } from 'react-native';

import { photoUrl } from './api';

// Поделиться ссылкой: системное меню «Поделиться», а если его нет (браузер на компьютере) — копируем.
export async function shareLink(message: string, url: string): Promise<'shared' | 'copied'> {
  if (Platform.OS === 'web') {
    const nav: any = typeof navigator !== 'undefined' ? navigator : null;
    if (nav?.share) {
      try {
        await nav.share({ text: message, url });
        return 'shared';
      } catch (e: any) {
        if (e?.name === 'AbortError') return 'shared';
      }
    }
    await Clipboard.setStringAsync(`${message} ${url}`);
    return 'copied';
  }
  await Share.share({ message: `${message} ${url}` });
  return 'shared';
}

// Поделиться карточкой результата (PNG): в сторис, мессенджер или сохранить.
export async function shareCard(path: string): Promise<'shared' | 'downloaded'> {
  const url = photoUrl(path);
  if (Platform.OS === 'web') {
    const blob = await (await fetch(url)).blob();
    const file = new (globalThis as any).File([blob], 'fithelper.png', { type: 'image/png' });
    const nav: any = navigator;
    if (nav?.canShare?.({ files: [file] })) {
      try {
        await nav.share({ files: [file] });
      } catch (e: any) {
        if (e?.name !== 'AbortError') throw e;
      }
      return 'shared';
    }
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = 'fithelper.png';
    a.click();
    return 'downloaded';
  }
  const dir = new Directory(Paths.cache, 'cards');
  if (!dir.exists) dir.create();
  const target = new File(dir, `card-${Date.now()}.png`);
  const file = await File.downloadFileAsync(url, target);
  await Sharing.shareAsync(file.uri, { mimeType: 'image/png', dialogTitle: 'Поделиться результатом' });
  return 'shared';
}
