import type { RawPost, TopicCluster, GravitySignal } from '../types';

// ── Stop words ──
const STOP = new Set([
  'the','a','an','and','or','but','in','on','at','to','for','of','with','by',
  'is','it','as','be','are','was','were','been','being','have','has','had',
  'do','does','did','will','would','could','should','can','may','might',
  'shall','not','no','so','if','then','than','that','this','these','those',
  'from','into','about','up','out','off','over','under','after','before',
  'between','through','during','its','i','you','he','she','we','they','my',
  'your','his','her','our','their','me','him','us','them','what','which',
  'who','whom','how','when','where','why','all','each','every','both','few',
  'more','most','other','some','such','only','own','same','just','also',
  'very','even','still','already','new','one','two','first','last','show',
  'hn','ask','tell','get','got','make','made','like','know','want','use',
  'using','used','via','now','here','there','way','back','see','look',
  'much','many','any','well','going','take','come','thing','things','really',
  'something','don','doesn','isn','wasn','aren','won','didn','haven','hasn',
  'http','https','www','com','org','io',
]);

function extractTerms(text: string): string[] {
  return text
    .toLowerCase()
    .replace(/[^a-z0-9\s-]/g, ' ')
    .split(/\s+/)
    .filter(w => w.length > 2 && !STOP.has(w));
}

function computeTermSignature(terms: string[]): Map<string, number> {
  const freq = new Map<string, number>();
  for (const t of terms) freq.set(t, (freq.get(t) || 0) + 1);
  return freq;
}

function jaccardSimilarity(a: Set<string>, b: Set<string>): number {
  let intersection = 0;
  for (const t of a) if (b.has(t)) intersection++;
  const union = a.size + b.size - intersection;
  return union === 0 ? 0 : intersection / union;
}

// ── Topic clustering ──
// Simple greedy clustering: group posts whose titles share enough terms
export function clusterPosts(posts: RawPost[]): TopicCluster[] {
  if (posts.length === 0) return [];

  // Extract term sets per post
  const postTerms = posts.map(p => ({
    post: p,
    terms: new Set(extractTerms(p.text || '')),
  }));

  // Greedy clustering
  const assigned = new Set<number>();
  const clusters: { posts: RawPost[]; allTerms: string[] }[] = [];

  for (let i = 0; i < postTerms.length; i++) {
    if (assigned.has(i)) continue;
    if (postTerms[i].terms.size === 0) continue;

    const cluster = { posts: [postTerms[i].post], allTerms: [...postTerms[i].terms] };
    assigned.add(i);

    for (let j = i + 1; j < postTerms.length; j++) {
      if (assigned.has(j)) continue;
      if (postTerms[j].terms.size === 0) continue;

      const sim = jaccardSimilarity(postTerms[i].terms, postTerms[j].terms);
      if (sim >= 0.2) {
        cluster.posts.push(postTerms[j].post);
        cluster.allTerms.push(...postTerms[j].terms);
        assigned.add(j);
      }
    }

    if (cluster.posts.length >= 2) {
      clusters.push(cluster);
    }
  }

  // Score and label each cluster
  const now = Date.now();
  const allClusterKeywords = clusters.map(c => new Set(c.allTerms));

  return clusters.map((c, idx) => {
    // Top keywords by frequency
    const freq = computeTermSignature(c.allTerms);
    const keywords = [...freq.entries()]
      .sort((a, b) => b[1] - a[1])
      .slice(0, 5)
      .map(([term]) => term);

    // Label from the highest-scored post title
    const bestPost = [...c.posts].sort((a, b) => b.score - a.score)[0];
    const label = bestPost.text?.slice(0, 80) || keywords.slice(0, 3).join(' ');

    // Velocity: compare last 24h vs prior 24h volume
    const h24 = 24 * 3600 * 1000;
    const recentPosts = c.posts.filter(p => now - new Date(p.created_at).getTime() < h24);
    const olderPosts = c.posts.filter(p => {
      const age = now - new Date(p.created_at).getTime();
      return age >= h24 && age < h24 * 2;
    });
    const recentVol = recentPosts.length;
    const olderVol = Math.max(olderPosts.length, 1);
    const velocity = ((recentVol - olderVol) / olderVol) * 100;

    // Sparkline: hourly buckets over last 72h
    const hours72 = 72;
    const buckets = new Array(hours72).fill(0);
    for (const p of c.posts) {
      const hoursAgo = (now - new Date(p.created_at).getTime()) / 3600000;
      const bucket = Math.floor(hoursAgo);
      if (bucket >= 0 && bucket < hours72) {
        buckets[hours72 - 1 - bucket]++;
      }
    }

    // Novelty: how unique are this cluster's keywords vs all other clusters
    const myKeySet = new Set(keywords);
    let maxOverlap = 0;
    for (let j = 0; j < allClusterKeywords.length; j++) {
      if (j === idx) continue;
      const overlap = jaccardSimilarity(myKeySet, allClusterKeywords[j]);
      if (overlap > maxOverlap) maxOverlap = overlap;
    }
    const novelty = 1 - maxOverlap;

    // Authors
    const authorCounts = new Map<string, number>();
    for (const p of c.posts) {
      const author = (p.metadata?.by as string) || (p.metadata?.author as string) || 'unknown';
      authorCounts.set(author, (authorCounts.get(author) || 0) + 1);
    }
    const topAuthors = [...authorCounts.entries()]
      .sort((a, b) => b[1] - a[1])
      .slice(0, 5)
      .map(([name, count]) => ({ name, count }));

    // Driver detection
    const driver = detectDriver(c.posts, topAuthors);

    // Inflection: velocity spike > 100% AND recent volume > 2
    const isInflection = velocity > 100 && recentVol >= 2;

    // Dominant source
    const sourceCounts = new Map<string, number>();
    for (const p of c.posts) sourceCounts.set(p.source, (sourceCounts.get(p.source) || 0) + 1);
    const dominantSource = [...sourceCounts.entries()].sort((a, b) => b[1] - a[1])[0]?.[0] || 'unknown';

    return {
      id: `cluster-${idx}`,
      label,
      keywords,
      posts: c.posts,
      velocity,
      velocityHistory: buckets,
      novelty,
      volume: c.posts.length,
      driver,
      isInflection,
      topAuthors,
      dominantSource,
      topUrl: bestPost.url,
    };
  });
}

function detectDriver(posts: RawPost[], topAuthors: { name: string; count: number }[]): string | null {
  const paperDomains = ['arxiv.org', 'paperswithcode.com', 'openreview.net'];
  const launchDomains = ['producthunt.com', 'techcrunch.com', 'venturebeat.com'];
  const benchmarkPatterns = ['sota', 'state-of-the-art', 'beats', 'surpasses', 'outperforms', 'benchmark'];

  const signals: Record<string, number> = { person: 0, new_paper: 0, new_repo: 0, product_launch: 0, benchmark: 0 };

  // Person-driven: >60% of posts from a single author
  if (topAuthors.length > 0) {
    const topAuthorShare = topAuthors[0].count / posts.length;
    if (topAuthorShare > 0.6) signals.person += 3;
  }

  for (const p of posts) {
    const url = (p.url || '').toLowerCase();
    const text = (p.text || '').toLowerCase();
    if (paperDomains.some(d => url.includes(d))) signals.new_paper++;
    if (url.includes('github.com')) signals.new_repo++;
    if (launchDomains.some(d => url.includes(d))) signals.product_launch++;
    if (['announces', 'launches', 'releases', 'introducing'].some(k => text.includes(k))) signals.product_launch++;
    if (benchmarkPatterns.some(k => text.includes(k))) signals.benchmark++;
  }

  const best = Object.entries(signals).sort((a, b) => b[1] - a[1])[0];
  return best && best[1] > 0 ? best[0] : null;
}

// ── Gravity detection ──
// Watched accounts: notable HN posters whose convergence on a topic is a signal
const WATCHED_ACCOUNTS = [
  'dang', 'pg', 'tptacek', 'patio11', 'jacquesm', 'raganwald',
  'cperciva', 'graydon', 'antirez', 'simonw', 'karpathy',
  'swyx', 'tlb', 'sama', 'natfriedman', 'amasad',
  // Add any authors we actually see in the data
  'zdw', 'rbanffy', 'benbreen', 'ingve', 'Brajeshwar',
];

export function detectGravity(clusters: TopicCluster[]): GravitySignal[] {
  const signals: GravitySignal[] = [];
  const watchedSet = new Set(WATCHED_ACCOUNTS.map(a => a.toLowerCase()));

  for (const cluster of clusters) {
    const watchedInCluster: { name: string; posts: number }[] = [];

    for (const { name, count } of cluster.topAuthors) {
      if (watchedSet.has(name.toLowerCase())) {
        watchedInCluster.push({ name, posts: count });
      }
    }

    if (watchedInCluster.length >= 1) {
      // Check timing spread for coordination heuristic
      const now = Date.now();
      const postTimes = cluster.posts
        .filter(p => {
          const author = ((p.metadata?.by as string) || '').toLowerCase();
          return watchedSet.has(author);
        })
        .map(p => new Date(p.created_at).getTime());

      let isCoordinated = false;
      if (postTimes.length >= 2) {
        const spread = Math.max(...postTimes) - Math.min(...postTimes);
        isCoordinated = spread < 2 * 3600 * 1000; // within 2 hours
      }

      signals.push({
        topic: cluster,
        watchedAccounts: watchedInCluster,
        convergenceStrength: watchedInCluster.length,
        window: '72h',
        isCoordinated,
      });
    }
  }

  // Sort by convergence strength
  signals.sort((a, b) => b.convergenceStrength - a.convergenceStrength);
  return signals;
}

// ── Helpers for tabs ──
export function getHeatmapTopics(clusters: TopicCluster[], limit = 10): TopicCluster[] {
  return [...clusters].sort((a, b) => b.velocity - a.velocity).slice(0, limit);
}

export function getInflections(clusters: TopicCluster[]): TopicCluster[] {
  return clusters.filter(c => c.isInflection).sort((a, b) => b.velocity - a.velocity);
}
