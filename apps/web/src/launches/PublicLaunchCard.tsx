import type { PublicLaunchPage } from "./client";

export type PublicLaunchCardItem = PublicLaunchPage["items"][number];

export function PublicLaunchCard({ item }: { item: PublicLaunchCardItem }) {
  const detailHref = `/launches/${encodeURIComponent(item.id)}`;

  return (
    <li className="launch-discovery-card">
      <a
        aria-label={item.logoUrl ? undefined : `LP logo for ${item.name}`}
        className="launch-discovery-card-link"
        href={detailHref}
      >
        {item.logoUrl ? (
          <img
            alt={item.name}
            decoding="async"
            loading="lazy"
            src={item.logoUrl}
          />
        ) : (
          <span aria-hidden="true" className="launch-discovery-logo-fallback">
            LP
          </span>
        )}
      </a>
      <div className="launch-discovery-card-content">
        <h3>
          <a href={detailHref}>{item.name}</a>
        </h3>
        <p className="launch-discovery-pitch">{item.pitch}</p>
        {item.topics.length > 0 ? (
          <ul
            aria-label={`${item.name} topics`}
            className="launch-discovery-topics"
          >
            {item.topics.map((topic) => (
              <li key={topic}>{topic}</li>
            ))}
          </ul>
        ) : null}
      </div>
    </li>
  );
}
