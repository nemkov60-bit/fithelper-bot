import { useState } from 'react';
import { View, type LayoutChangeEvent } from 'react-native';
import Svg, { Circle, Line, Polygon, Polyline } from 'react-native-svg';

import { colors } from '../lib/theme';

// Простой линейный график (вес тела).
export function LineChart({ values, height = 170, label }: { values: number[]; height?: number; label: string }) {
  const [width, setWidth] = useState(300);
  const onLayout = (e: LayoutChangeEvent) => setWidth(e.nativeEvent.layout.width);
  if (values.length < 2) {
    return <View style={{ height }} onLayout={onLayout} />;
  }
  const lo = Math.min(...values) - 1;
  const hi = Math.max(...values) + 1;
  const pad = 8;
  const pts = values.map((v, i) => [
    pad + (i * (width - pad * 2)) / (values.length - 1),
    height - 20 - ((v - lo) / (hi - lo)) * (height - 40),
  ]);
  const line = pts.map((p) => p.join(',')).join(' ');
  const last = pts[pts.length - 1];
  return (
    <View onLayout={onLayout} accessible accessibilityLabel={label}>
      <Svg width={width} height={height}>
        {[0.25, 0.5, 0.75].map((f) => (
          <Line key={f} x1={0} x2={width} y1={height * f} y2={height * f} stroke={colors.border} strokeWidth={1} />
        ))}
        <Polygon points={`${pad},${height} ${line} ${width - pad},${height}`} fill={colors.accent} fillOpacity={0.12} />
        <Polyline points={line} fill="none" stroke={colors.accent} strokeWidth={3} strokeLinejoin="round" strokeLinecap="round" />
        <Circle cx={last[0]} cy={last[1]} r={6} fill={colors.accent} />
      </Svg>
    </View>
  );
}
