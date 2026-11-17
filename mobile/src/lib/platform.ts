import { Platform } from 'react-native';

// Сборка для App Store: никаких цен, тарифов, кнопок покупки и упоминаний оплаты вне App Store
// (правила Apple 3.1.1 / 3.1.3). Подписка, купленная на сайте или в боте, просто действует после входа.
// Веб-версия (в том числе в Safari на iPhone) и Android показывают всё как есть.
export const IOS_STORE = Platform.OS === 'ios';
