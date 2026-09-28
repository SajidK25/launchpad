import { FormEvent, useEffect, useMemo, useState } from "react";

import type { IdentityClient } from "../identity/client";
import { navigate } from "../identity/Screens";
import {
  createProfileClient,
  ProfileRequestError,
  type ProfilePatch,
} from "./client";
import {
  useCompletePhotoUpload,
  useCreatePhotoUpload,
  usePublicProfile,
  usePublishProfile,
  useUnpublishProfile,
  useUpdateProfile,
  useViewerProfile,
} from "./useProfile";

const MAX_PHOTO_BYTES = 5 * 1024 * 1024;
const PHOTO_TYPES = new Set(["image/jpeg", "image/png", "image/webp"]);

export function ProfileRoutes({
  identityClient,
}: {
  identityClient: IdentityClient;
}) {
  const client = useMemo(
    () => createProfileClient(undefined, identityClient.getCsrfToken),
    [identityClient],
  );
  const path = window.location.pathname;
  if (path.startsWith("/public/"))
    return <PublicProfilePage client={client} accountId={path.slice(8)} />;
  return <ProfileEditorPage client={client} />;
}

function ProfileEditorPage({
  client,
}: {
  client: ReturnType<typeof createProfileClient>;
}) {
  const profile = useViewerProfile(client);
  const update = useUpdateProfile(client);
  const publish = usePublishProfile(client);
  const unpublish = useUnpublishProfile(client);
  const createUpload = useCreatePhotoUpload(client);
  const completeUpload = useCompletePhotoUpload(client);
  const [displayName, setDisplayName] = useState("");
  const [bio, setBio] = useState("");
  const [links, setLinks] = useState("");
  const [photoUploadId, setPhotoUploadId] = useState<string | null>(null);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    if (profile.data) {
      setDisplayName(profile.data.displayName);
      setBio(profile.data.bio);
      setLinks(profile.data.links.join("\n"));
    }
  }, [profile.data]);

  const linkValues = links
    .split("\n")
    .map((link) => link.trim())
    .filter(Boolean);
  const completeness = {
    name: displayName.trim().length > 0,
    bio: bio.trim().length > 0 && bio.length <= 160,
    link: linkValues.some((link) => isHttpsUrl(link)),
    photo: Boolean(profile.data?.photoUrl || photoUploadId),
  };
  const complete = Object.values(completeness).every(Boolean);

  if (profile.isPending)
    return (
      <ProfileShell title="Your profile">
        <p role="status">Loading your private profile…</p>
      </ProfileShell>
    );
  if (profile.isError || !profile.data)
    return (
      <ProfileShell title="Your profile">
        <p role="alert">
          Your private profile is unavailable. Please sign in again.
        </p>
        <button
          className="secondary-button"
          onClick={() => navigate("/signin")}
          type="button"
        >
          Sign in
        </button>
      </ProfileShell>
    );
  const viewer = profile.data;

  async function save(event: FormEvent) {
    event.preventDefault();
    setError("");
    setNotice("");
    if (bio.length > 160)
      return setError("Bio must be 160 characters or fewer.");
    if (linkValues.some((link) => !isHttpsUrl(link)))
      return setError("Each link must be a public HTTPS URL.");
    try {
      const patch: ProfilePatch = {
        version: viewer.version,
        display_name: displayName.trim() || null,
        bio: bio.trim() || null,
        links: linkValues,
      };
      if (photoUploadId !== null) patch.photo_upload_id = photoUploadId;
      const result = await update.mutateAsync(patch);
      setNotice(
        result &&
          typeof result === "object" &&
          "became_private" in result &&
          result.became_private
          ? "Your edit was saved and the profile is private. We’ll email you when the privacy notice is delivered."
          : "Your private profile was saved.",
      );
      setPhotoUploadId(null);
    } catch (caught) {
      setError(
        caught instanceof ProfileRequestError && caught.status === 409
          ? "This profile changed elsewhere. Refresh and try again."
          : "We could not save your profile. Please try again.",
      );
    }
  }

  async function handlePhoto(file: File | undefined) {
    if (!file) return;
    setError("");
    setNotice("");
    if (!PHOTO_TYPES.has(file.type) || file.size > MAX_PHOTO_BYTES)
      return setError("Use a JPEG, PNG, or WebP image up to 5 MB.");
    try {
      const intent = await createUpload.mutateAsync({
        filename: file.name,
        content_type: file.type,
        size: file.size,
      });
      const form = new FormData();
      Object.entries(intent.fields).forEach(([key, value]) =>
        form.append(key, value),
      );
      form.append("file", file);
      const response = await fetch(intent.upload_url, {
        method: "POST",
        body: form,
      });
      if (!response.ok) throw new Error("staging upload failed");
      const completed = await completeUpload.mutateAsync(intent.upload_id);
      setPhotoUploadId(completed.upload_id);
      setNotice("Photo validated. Save your profile to attach it.");
    } catch {
      setError(
        "Photo upload could not be completed. Check the file and try again.",
      );
    }
  }

  async function changeVisibility(action: "publish" | "unpublish") {
    setError("");
    setNotice("");
    try {
      const result = await (action === "publish"
        ? publish.mutateAsync(viewer.version)
        : unpublish.mutateAsync(viewer.version));
      setNotice(
        result &&
          typeof result === "object" &&
          "became_private" in result &&
          result.became_private
          ? "This profile is private until all required information is complete."
          : action === "publish"
            ? "Your profile is public."
            : "Your profile is private.",
      );
    } catch {
      setError(
        action === "publish"
          ? "Your profile must be complete and your email verified before publishing."
          : "We could not change profile visibility. Please try again.",
      );
    }
  }

  return (
    <ProfileShell title="Your profile">
      <p className="identity-intro">
        Your draft stays private until you choose to publish a complete profile.
      </p>
      <form className="identity-form" onSubmit={save}>
        <label className="form-field" htmlFor="profile-name">
          <span>Display name</span>
          <input
            id="profile-name"
            aria-describedby={error ? "profile-error" : undefined}
            aria-invalid={Boolean(error) || undefined}
            value={displayName}
            onChange={(event) => setDisplayName(event.target.value)}
          />
        </label>
        <label className="form-field" htmlFor="profile-bio">
          <span>
            One-line bio <small>({bio.length}/160)</small>
          </span>
          <textarea
            aria-describedby={error ? "profile-error" : undefined}
            aria-invalid={Boolean(error) || undefined}
            id="profile-bio"
            maxLength={160}
            rows={3}
            value={bio}
            onChange={(event) => setBio(event.target.value)}
          />
        </label>
        <label className="form-field" htmlFor="profile-links">
          <span>
            Public HTTPS links <small>one per line</small>
          </span>
          <textarea
            aria-describedby={error ? "profile-error" : undefined}
            aria-invalid={Boolean(error) || undefined}
            id="profile-links"
            rows={3}
            value={links}
            onChange={(event) => setLinks(event.target.value)}
          />
        </label>
        <label className="form-field" htmlFor="profile-photo">
          <span>
            Profile photo <small>JPEG, PNG, or WebP up to 5 MB</small>
          </span>
          <input
            accept="image/jpeg,image/png,image/webp"
            aria-describedby={error ? "profile-error" : undefined}
            aria-invalid={Boolean(error) || undefined}
            id="profile-photo"
            onChange={(event) => void handlePhoto(event.target.files?.[0])}
            type="file"
          />
        </label>
        <ul className="profile-checklist" aria-label="Publication requirements">
          <li className={completeness.name ? "complete" : "incomplete"}>
            Display name
          </li>
          <li className={completeness.photo ? "complete" : "incomplete"}>
            Validated photo
          </li>
          <li className={completeness.bio ? "complete" : "incomplete"}>
            Bio up to 160 characters
          </li>
          <li className={completeness.link ? "complete" : "incomplete"}>
            At least one HTTPS link
          </li>
        </ul>
        <button
          aria-describedby={error ? "profile-error" : undefined}
          className="primary-button"
          disabled={update.isPending}
          type="submit"
        >
          {update.isPending ? "Saving…" : "Save private profile"}
        </button>
      </form>
      <div className="profile-actions" aria-label="Profile visibility actions">
        {viewer.visibility === "public" ? (
          <button
            aria-describedby={error ? "profile-error" : undefined}
            className="secondary-button"
            disabled={unpublish.isPending}
            onClick={() => void changeVisibility("unpublish")}
            type="button"
          >
            Make profile private
          </button>
        ) : (
          <button
            aria-describedby={error ? "profile-error" : undefined}
            className="secondary-button"
            disabled={!complete || publish.isPending}
            onClick={() => void changeVisibility("publish")}
            type="button"
          >
            Publish profile
          </button>
        )}
      </div>
      <ProfileMessage message={notice} />
      <ProfileMessage error id="profile-error" message={error} />
      {viewer.visibility === "public" ? (
        <a className="back-link" href={`/public/${viewer.accountId}`}>
          View public profile
        </a>
      ) : null}
    </ProfileShell>
  );
}

function PublicProfilePage({
  client,
  accountId,
}: {
  client: ReturnType<typeof createProfileClient>;
  accountId: string;
}) {
  const profile = usePublicProfile(client, accountId);
  if (profile.isPending)
    return (
      <ProfileShell title="Member profile">
        <p role="status">Loading profile…</p>
      </ProfileShell>
    );
  if (profile.isError || !profile.data)
    return (
      <ProfileShell title="Member profile">
        <p role="status">This profile is private or unavailable.</p>
      </ProfileShell>
    );
  return (
    <ProfileShell title={profile.data.displayName}>
      <p className="profile-bio">{profile.data.bio}</p>
      {profile.data.photoUrl ? (
        <img
          alt={`${profile.data.displayName} profile`}
          className="profile-photo"
          src={profile.data.photoUrl}
        />
      ) : null}
      <ul className="public-links">
        {profile.data.links.map((link) => (
          <li key={link}>
            <a href={link} rel="noreferrer" target="_blank">
              {link}
            </a>
          </li>
        ))}
      </ul>
    </ProfileShell>
  );
}

function ProfileShell({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <main className="page-shell identity-shell">
      <section
        aria-labelledby="profile-title"
        className="identity-card profile-card"
      >
        <p className="eyebrow">Launchpad profile</p>
        <h1 id="profile-title">{title}</h1>
        {children}
      </section>
    </main>
  );
}

function ProfileMessage({
  id,
  message,
  error = false,
}: {
  id?: string;
  message: string;
  error?: boolean;
}) {
  return message ? (
    <p
      aria-live="polite"
      className={error ? "form-message form-error" : "form-message"}
      id={id}
      role={error ? "alert" : "status"}
    >
      {message}
    </p>
  ) : null;
}

function isHttpsUrl(value: string) {
  try {
    return new URL(value).protocol === "https:";
  } catch {
    return false;
  }
}
