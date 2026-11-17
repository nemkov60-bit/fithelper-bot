import {
  Manrope_400Regular, Manrope_500Medium, Manrope_600SemiBold, Manrope_700Bold, Manrope_800ExtraBold, useFonts,
} from '@expo-google-fonts/manrope';
import { Stack } from 'expo-router';
import { StatusBar } from 'expo-status-bar';
import { SafeAreaProvider } from 'react-native-safe-area-context';

import { Loading } from '../components/ui';
import { AuthProvider } from '../lib/auth';
import { colors } from '../lib/theme';

export default function RootLayout() {
  const [loaded] = useFonts({ Manrope_400Regular, Manrope_500Medium, Manrope_600SemiBold, Manrope_700Bold, Manrope_800ExtraBold });
  return (
    <SafeAreaProvider>
      <StatusBar style="light" />
      {loaded ? (
        <AuthProvider>
          <Stack screenOptions={{ headerShown: false, contentStyle: { backgroundColor: colors.bg } }}>
            <Stack.Screen name="workout" options={{ gestureEnabled: false }} />
          </Stack>
        </AuthProvider>
      ) : <Loading />}
    </SafeAreaProvider>
  );
}
