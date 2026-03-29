interface NoveltyBarProps {
  value: number; // 0–1
}

export function NoveltyBar({ value }: NoveltyBarProps) {
  const pct = Math.round(value * 100);
  return (
    <div className="novelty-bar-container">
      <span className="novelty-label">Novelty</span>
      <div className="novelty-track">
        <div className="novelty-fill" style={{ width: `${pct}%` }} />
      </div>
      <span className="novelty-value">{pct}%</span>
    </div>
  );
}
