const DRIVER_LABELS: Record<string, { label: string; fragile?: boolean }> = {
  person: { label: 'Person', fragile: true },
  new_paper: { label: 'Paper' },
  new_repo: { label: 'Repo' },
  product_launch: { label: 'Launch' },
  benchmark: { label: 'Benchmark' },
};

interface DriverTagProps {
  driver: string;
}

export function DriverTag({ driver }: DriverTagProps) {
  const info = DRIVER_LABELS[driver] || { label: driver };
  return (
    <span className={`driver-tag ${info.fragile ? 'fragile' : ''}`}>
      {info.label}
      {info.fragile && <span className="fragile-marker" title="Potentially fragile — tied to one account">!</span>}
    </span>
  );
}
