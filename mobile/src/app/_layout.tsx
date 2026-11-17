import {
  Manrope_400Regular, Manrope_500Medium, Manrope_600SemiBold, Manrope_700Bold, Manrope_800ExtraBold, useFonts,
} from '@expo-google-fonts/manrope';
import { Stack } from 'expo-router';
import { StatusBar } from 'expo-status-bar';
import { SafeAreaProvider } from 'react-native-safe-area-context';

import { Loading } from '../components/ui';
import { AuthProvider } from '../lib/auth';
import { colors } from '../lib/theme';
import { ThemeProvider } from '../lib/themeContext';

export default function RootLayout() {
  const [loaded] = useFonts({ Manrope_400Regular, Manrope_500Medium, Manrope_600SemiBold, Manrope_700Bold, Manrope_800ExtraBold });
  return (
    <SafeAreaProvider>
      {loaded ? (
        <AuthProvider>
          <ThemeProvider>
            <Themed />
          </ThemeProvider>
        </AuthProvider>
      ) : <Loading />}
    </SafeAreaProvider>
  );
}

function Themed() {
  if (typeof document !== 'undefined') document.body.style.backgroundColor = colors.bg;
  return (
    <>
      <StatusBar style={colors.light ? 'dark' : 'light'} />
      <Stack screenOptions={{ headerShown: false, contentStyle: { backgroundColor: colors.bg } }}>
        <Stack.Screen name="workout" options={{ gestureEnabled: false }} />
      </Stack>
    </>
  );
}
