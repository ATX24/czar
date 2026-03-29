import type { TopicCluster } from '../types';
import { Sparkline } from './Sparkline';
import { NoveltyBar } from './NoveltyBar';
import { DriverTag } from './DriverTag';

interface TopicCardProps {
  topic: TopicCluster;
  rank?: number;
  showGravityInfo?: {
    watchedAccounts: { name: string; posts: number }[];
    isCoordinated: boolean;
  };
}

function formatVelocity(v: number): string {
  const sign = v >= 0 ? '+' : '';
  return `${sign}${Math.round(v)}%`;
}

export function TopicCard({ topic, rank, showGravityInfo }: TopicCardProps) {
  return (
    <article className="topic-card">
      <div className="card-header">
        <div className="card-rank-velocity">
          {rank != null && <span className="card-rank">{rank}</span>}
          <span className={`card-velocity ${topic.velocity >= 0 ? 'up' : 'down'}`}>
            {formatVelocity(topic.velocity)}
          </span>
        </div>
        <div className="card-tags">
          {topic.driver && <DriverTag driver={topic.driver} />}
          <span className="source-tag">{topic.dominantSource.toUpperCase()}</span>
          <span className="volume-tag">{topic.volume} posts</span>
        </div>
      </div>

      <a
        href={topic.topUrl || '#'}
        target="_blank"
        rel="noopener noreferrer"
        className="card-title"
      >
        {topic.label}
      </a>

      <div className="card-keywords">
        {topic.keywords.map(k => (
          <span key={k} className="keyword-chip">{k}</span>
        ))}
      </div>

      <div className="card-signals">
        <div className="signal-sparkline">
          <span className="signal-label">72h Activity</span>
          <Sparkline data={topic.velocityHistory} />
        </div>
        <div className="signal-novelty">
          <NoveltyBar value={topic.novelty} />
        </div>
      </div>

      {showGravityInfo && (
        <div className="card-gravity">
          <span className="gravity-label">Watched Accounts</span>
          <div className="gravity-accounts">
            {showGravityInfo.watchedAccounts.map(a => (
              <span key={a.name} className="gravity-account">
                {a.name} <span className="gravity-count">({a.posts})</span>
              </span>
            ))}
          </div>
          {!showGravityInfo.isCoordinated && (
            <span className="gravity-note">No coordinated push</span>
          )}
          {showGravityInfo.isCoordinated && (
            <span className="gravity-note coordinated">Timing suggests coordination</span>
          )}
        </div>
      )}

      <div className="card-authors">
        {topic.topAuthors.slice(0, 3).map(a => (
          <span key={a.name} className="author-chip">{a.name}</span>
        ))}
      </div>
    </article>
  );
}
