import { Linking, Platform } from 'react-native';

import { API_URL } from './api';

export const PRIVACY_URL = `${API_URL || (typeof location !== 'undefined' ? location.origin : '')}/privacy`;

export function openPrivacy() {
  if (Platform.OS === 'web') globalThis.open?.(PRIVACY_URL, '_blank');
  else Linking.openURL(PRIVACY_URL);
}
