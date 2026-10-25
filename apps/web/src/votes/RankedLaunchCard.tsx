import type { DailyRankingItem } from "../launches/client";
import type { IdentityClient } from "../identity/client";
import { VoteControl } from "./VoteControl";

export function RankedLaunchCard({
  item,
  identityClient,
  launchDate,
  headingLevel = "h3",
  votingOpen = false,
}: {
  item: DailyRankingItem;
  identityClient?: IdentityClient;
  launchDate?: string;
  headingLevel?: "h2" | "h3";
  votingOpen?: boolean;
}) {
  const { product } = item;
  const Heading = headingLevel;
  return (
    <li className="launch-discovery-card ranked-launch-card">
      <a
        aria-label={product.logoUrl ? undefined : `LP logo for ${product.name}`}
        className="launch-discovery-card-link"
        href={`/launches/${encodeURIComponent(product.id)}`}
      >
        {product.logoUrl ? (
          <img alt={product.name} loading="lazy" src={product.logoUrl} />
        ) : (
          <span aria-hidden="true" className="launch-discovery-logo-fallback">
            {product.name.slice(0, 1).toUpperCase()}
          </span>
        )}
      </a>
      <div className="launch-discovery-card-content">
        <div className="ranked-launch-card-meta">
          <span
            aria-atomic="true"
            aria-live="polite"
            className="ranked-launch-rank"
          >
            {item.rank === null ? "UNRANKED" : `RANK #${item.rank}`}
          </span>
          {item.activeVoteCount === null ? null : (
            <span className="ranked-launch-votes">
              {item.activeVoteCount}{" "}
              {item.activeVoteCount === 1 ? "vote" : "votes"}
            </span>
          )}
        </div>
        <Heading>
          <a href={`/launches/${encodeURIComponent(product.id)}`}>
            {product.name}
          </a>
        </Heading>
        <p className="launch-discovery-pitch">{product.pitch}</p>
        {product.topics.length > 0 ? (
          <ul aria-label="Product topics" className="launch-discovery-topics">
            {product.topics.map((topic) => (
              <li key={topic}>{topic}</li>
            ))}
          </ul>
        ) : null}
        {identityClient && launchDate ? (
          <VoteControl
            activeVoteCount={item.activeVoteCount}
            identityClient={identityClient}
            launchDate={launchDate}
            productId={product.id}
            viewerVoted={item.viewerVoted}
            votingOpen={votingOpen}
          />
        ) : null}
      </div>
    </li>
  );
}
