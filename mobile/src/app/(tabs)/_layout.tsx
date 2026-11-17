import { Redirect } from 'expo-router';
import { Tabs, type BottomTabBarProps } from 'expo-router/js-tabs';
import { Pressable, Text, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { Icon, type IconName } from '../../components/Icon';
import { useAuth } from '../../lib/auth';
import { colors, fonts } from '../../lib/theme';

const TABS: Record<string, { label: string; icon: IconName }> = {
  home: { label: 'Главная', icon: 'home' },
  progress: { label: 'Прогресс', icon: 'chart' },
  coach: { label: 'Тренер', icon: 'coach' },
  profile: { label: 'Профиль', icon: 'user' },
};

// Нижнее меню-«таблетка» как в прототипе: активный раздел — салатовая кнопка с подписью.
function PillTabBar({ state, navigateToTab }: BottomTabBarProps) {
  const insets = useSafeAreaInsets();
  return (
    <View style={{ position: 'absolute', left: 16, right: 16, bottom: Math.max(insets.bottom, 12) + 8 }}>
      <View style={{
        height: 68, borderRadius: 999, backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border,
        flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', paddingHorizontal: 8,
      }}>
        {state.routes.map((route, index) => {
          const tab = TABS[route.name];
          if (!tab) return null;
          const focused = state.index === index;
          const onPress = () => {
            if (!focused) navigateToTab(route.key);
          };
          return focused ? (
            <Pressable key={route.key} accessibilityRole="tab" accessibilityState={{ selected: true }} onPress={onPress}
              style={{ flexDirection: 'row', alignItems: 'center', gap: 8, height: 52, paddingHorizontal: 18, borderRadius: 999, backgroundColor: colors.accent }}>
              <Icon name={tab.icon} size={20} color={colors.onAccent} strokeWidth={2.2} />
              <Text style={{ fontFamily: fonts.extrabold, fontSize: 14, color: colors.onAccent }}>{tab.label}</Text>
            </Pressable>
          ) : (
            <Pressable key={route.key} accessibilityRole="tab" accessibilityLabel={tab.label} onPress={onPress}
              style={{ width: 52, height: 52, borderRadius: 26, alignItems: 'center', justifyContent: 'center' }}>
              <Icon name={tab.icon} size={22} />
            </Pressable>
          );
        })}
      </View>
    </View>
  );
}

export default function TabsLayout() {
  const { ready, me } = useAuth();
  if (ready && !me) return <Redirect href="/login" />;
  if (ready && me && !me.profile_complete) return <Redirect href="/onboarding" />;
  return (
    <Tabs tabBar={(props) => <PillTabBar {...props} />} screenOptions={{ headerShown: false, sceneStyle: { backgroundColor: colors.bg } }}>
      <Tabs.Screen name="home" />
      <Tabs.Screen name="progress" />
      <Tabs.Screen name="coach" />
      <Tabs.Screen name="profile" />
    </Tabs>
  );
}
