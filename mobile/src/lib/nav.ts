import { router, type Href } from 'expo-router';

// «Назад»: если экран открыт напрямую (ссылкой, после перезагрузки или из уведомления),
// истории нет и router.back() ничего не делает — тогда уходим на понятный экран.
export function goBack(fallback: Href = '/home') {
  if (router.canGoBack()) router.back();
  else router.replace(fallback);
}
