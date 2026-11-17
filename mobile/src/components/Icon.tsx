import Svg, { Circle, Path, Rect } from 'react-native-svg';

import { colors } from '../lib/theme';

export type IconName =
  | 'home' | 'dumbbell' | 'chart' | 'coach' | 'user' | 'back' | 'play' | 'check' | 'flame'
  | 'send' | 'plus' | 'minus' | 'swap' | 'book' | 'arrow' | 'close' | 'calendar' | 'group';

const PATHS: Record<IconName, (c: string) => React.ReactNode> = {
  home: (c) => <Path d="M3 11l9-7 9 7v9a1 1 0 0 1-1 1h-5v-6H9v6H4a1 1 0 0 1-1-1z" stroke={c} />,
  dumbbell: (c) => <Path d="M6.5 6.5v11M17.5 6.5v11M3 9.5v5M21 9.5v5M6.5 12h11" stroke={c} />,
  chart: (c) => <Path d="M3 20h18M6 16l4-5 3 3 5-7" stroke={c} />,
  coach: (c) => (
    <>
      <Circle cx="9" cy="8" r="4" stroke={c} />
      <Path d="M2 21c0-4 3-6 7-6s7 2 7 6M16 11l2 2 4-4" stroke={c} />
    </>
  ),
  user: (c) => (
    <>
      <Circle cx="12" cy="8" r="4" stroke={c} />
      <Path d="M4 21c0-4 4-6 8-6s8 2 8 6" stroke={c} />
    </>
  ),
  back: (c) => <Path d="M15 6l-6 6 6 6" stroke={c} />,
  play: (c) => <Path d="M8 5.5l11 6.5-11 6.5z" fill={c} stroke={c} />,
  check: (c) => <Path d="M5 12l5 5 9-10" stroke={c} />,
  flame: (c) => <Path d="M12 22c4 0 7-3 7-7 0-4-3-6-4-10-2 2-2 4-3 5-1-2-1-3-3-5 0 3-4 5-4 10 0 4 3 7 7 7z" stroke={c} />,
  send: (c) => <Path d="M5 12h14M13 6l6 6-6 6" stroke={c} />,
  arrow: (c) => <Path d="M5 12h14M13 6l6 6-6 6" stroke={c} />,
  plus: (c) => <Path d="M12 5v14M5 12h14" stroke={c} />,
  minus: (c) => <Path d="M5 12h14" stroke={c} />,
  swap: (c) => <Path d="M4 8h13l-3-3M20 16H7l3 3" stroke={c} />,
  book: (c) => <Path d="M4 5a2 2 0 0 1 2-2h12v16H6a2 2 0 0 0-2 2zM8 7h6" stroke={c} />,
  close: (c) => <Path d="M6 6l12 12M18 6L6 18" stroke={c} />,
  calendar: (c) => (
    <>
      <Rect x="3" y="5" width="18" height="16" rx="3" stroke={c} />
      <Path d="M8 3v4M16 3v4M3 10h18" stroke={c} />
    </>
  ),
  group: (c) => (
    <>
      <Circle cx="9" cy="8" r="4" stroke={c} />
      <Path d="M2 21c0-4 3-6 7-6s7 2 7 6M17 4a4 4 0 0 1 0 8M22 21c0-3-2-5-4-5.5" stroke={c} />
    </>
  ),
};

export function Icon({ name, size = 22, color = colors.soft, strokeWidth = 2 }: {
  name: IconName; size?: number; color?: string; strokeWidth?: number;
}) {
  return (
    <Svg width={size} height={size} viewBox="0 0 24 24" fill="none" strokeWidth={strokeWidth}
      strokeLinecap="round" strokeLinejoin="round" accessibilityElementsHidden importantForAccessibility="no">
      {PATHS[name](color)}
    </Svg>
  );
}
