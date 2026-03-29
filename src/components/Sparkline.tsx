interface SparklineProps {
  data: number[];
  width?: number;
  height?: number;
}

export function Sparkline({ data, width = 120, height = 28 }: SparklineProps) {
  if (data.length === 0) return null;

  const max = Math.max(...data, 1);
  const step = width / (data.length - 1 || 1);
  const points = data.map((v, i) => `${i * step},${height - (v / max) * height}`).join(' ');

  // Fill area
  const fillPoints = `0,${height} ${points} ${width},${height}`;

  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} className="sparkline">
      <polygon points={fillPoints} fill="rgba(0,0,0,0.06)" />
      <polyline points={points} fill="none" stroke="#000" strokeWidth="1.5" />
    </svg>
  );
}
