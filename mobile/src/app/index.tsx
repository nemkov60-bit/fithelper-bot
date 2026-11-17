import { Redirect } from 'expo-router';

import { Loading } from '../components/ui';
import { useAuth } from '../lib/auth';

// Точка входа: куда отправить пользователя.
export default function Index() {
  const { ready, me } = useAuth();
  if (!ready) return <Loading />;
  if (!me) return <Redirect href="/login" />;
  if (!me.profile_complete) return <Redirect href="/onboarding" />;
  return <Redirect href="/home" />;
}
