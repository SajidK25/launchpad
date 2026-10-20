import type { ButtonHTMLAttributes, ReactNode } from "react";

export type PageHeadingProps = {
  title: string;
  eyebrow?: string;
  description?: string;
  actions?: ReactNode;
};

export type PanelProps = {
  as?: "section" | "article";
  title?: string;
  headingLevel?: 2 | 3 | 4;
  children: ReactNode;
};

type ActionVariant = "primary" | "secondary" | "quiet" | "danger";

type ActionLinkProps = {
  href: string;
  children: ReactNode;
  variant?: ActionVariant;
  className?: string;
};

type ActionButtonProps = Omit<
  ButtonHTMLAttributes<HTMLButtonElement>,
  "className"
> & {
  href?: never;
  variant?: ActionVariant;
  className?: string;
};

export type ActionProps = ActionLinkProps | ActionButtonProps;

export type PaginationProps = {
  page: number;
  pageCount: number;
  onPrevious: () => void;
  onNext: () => void;
};

export type StatusBannerVariant =
  | "neutral"
  | "primary"
  | "success"
  | "warning"
  | "danger"
  | "info";

type StateProps = {
  title: string;
  description: string;
  action?: ReactNode;
};

export function PageHeading({
  title,
  eyebrow,
  description,
  actions,
}: PageHeadingProps) {
  return (
    <header className="ui-page-heading">
      <div className="ui-page-heading-copy">
        {eyebrow ? <p className="ui-eyebrow">{eyebrow}</p> : null}
        <h1>{title}</h1>
        {description ? <p>{description}</p> : null}
      </div>
      {actions ? (
        <div className="ui-page-heading-actions">{actions}</div>
      ) : null}
    </header>
  );
}

export function Panel({
  as = "section",
  title,
  headingLevel = 2,
  children,
}: PanelProps) {
  const Element = as;
  const Heading = `h${headingLevel}` as const;

  return (
    <Element className="ui-panel">
      {title ? <Heading className="ui-panel-title">{title}</Heading> : null}
      {children}
    </Element>
  );
}

export function Action(props: ActionProps) {
  const className = [
    "ui-action",
    `ui-action--${props.variant ?? "secondary"}`,
    props.className,
  ]
    .filter(Boolean)
    .join(" ");

  if ("href" in props && typeof props.href === "string") {
    return (
      <a className={className} href={props.href}>
        {props.children}
      </a>
    );
  }

  const buttonProps = { ...props };
  delete buttonProps.variant;
  delete buttonProps.className;
  return (
    <button className={className} type="button" {...buttonProps}>
      {props.children}
    </button>
  );
}

export function Pagination({
  page,
  pageCount,
  onPrevious,
  onNext,
}: PaginationProps) {
  const safePageCount = Math.max(0, pageCount);
  const safePage = Math.min(Math.max(1, page), safePageCount || 1);
  const previousDisabled = safePage <= 1;
  const nextDisabled = safePageCount === 0 || safePage >= safePageCount;

  return (
    <nav className="ui-pagination" aria-label="Pagination">
      <button
        className="ui-action ui-action--secondary"
        type="button"
        disabled={previousDisabled}
        onClick={onPrevious}
      >
        Previous page
      </button>
      <span aria-live="polite">
        Page {safePage} of {safePageCount}
      </span>
      <button
        className="ui-action ui-action--secondary"
        type="button"
        disabled={nextDisabled}
        onClick={onNext}
      >
        Next page
      </button>
    </nav>
  );
}

export function StatusBanner({
  variant,
  children,
}: {
  variant: StatusBannerVariant;
  children: ReactNode;
}) {
  const urgent = variant === "warning" || variant === "danger";
  const className = `ui-status-banner ui-status-banner--${variant}`;

  return urgent ? (
    <div className={className} role="alert">
      {children}
    </div>
  ) : (
    <div className={className} role="status">
      {children}
    </div>
  );
}

export function LoadingState({ title, description }: StateProps) {
  return (
    <section
      className="ui-state ui-loading-state"
      role="status"
      aria-live="polite"
    >
      <h2>{title}</h2>
      <p>{description}</p>
    </section>
  );
}

export function EmptyState({ title, description, action }: StateProps) {
  return (
    <section
      className="ui-state ui-empty-state"
      aria-labelledby="ui-empty-title"
    >
      <h2 id="ui-empty-title">{title}</h2>
      <p>{description}</p>
      {action ? <div className="ui-state-actions">{action}</div> : null}
    </section>
  );
}

export function UnavailableState({ title, description, action }: StateProps) {
  return (
    <section
      className="ui-state ui-unavailable-state"
      aria-labelledby="ui-unavailable-title"
    >
      <h2 id="ui-unavailable-title">{title}</h2>
      <p>{description}</p>
      {action ? <div className="ui-state-actions">{action}</div> : null}
    </section>
  );
}
