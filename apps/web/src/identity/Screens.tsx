import { FormEvent, useEffect, useState } from "react";

import type { IdentityClient } from "./client";
import {
  useLogin,
  useRegister,
  useRequestPasswordReset,
  useRequestVerification,
  useLogout,
  useResetPassword,
  useVerify,
} from "./useIdentity";

type Screen =
  | "signin"
  | "register"
  | "verify"
  | "recovery"
  | "reset"
  | "profile";

export function navigate(path: string) {
  window.history.pushState({}, "", path);
  window.dispatchEvent(new PopStateEvent("popstate"));
}

function usePath() {
  const [path, setPath] = useState(window.location.pathname);
  useEffect(() => {
    const update = () => setPath(window.location.pathname);
    window.addEventListener("popstate", update);
    return () => window.removeEventListener("popstate", update);
  }, []);
  return path;
}

function screenForPath(path: string): Screen {
  if (path === "/register") return "register";
  if (path === "/verify") return "verify";
  if (path === "/recover") return "recovery";
  if (path === "/reset") return "reset";
  if (path === "/profile") return "profile";
  return "signin";
}

export function IdentityRoutes({ client }: { client: IdentityClient }) {
  const screen = screenForPath(usePath());
  if (screen === "register") return <RegisterPage client={client} />;
  if (screen === "verify") return <VerifyPage client={client} />;
  if (screen === "recovery") return <RecoveryPage client={client} />;
  if (screen === "reset") return <ResetPage client={client} />;
  if (screen === "profile") return <PrivateProfileLanding client={client} />;
  return <SignInPage client={client} />;
}

function Page({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <main className="page-shell identity-shell">
      <section aria-labelledby="identity-title" className="identity-card">
        <p className="eyebrow">Launchpad account</p>
        <h1 id="identity-title">{title}</h1>
        {children}
      </section>
    </main>
  );
}

function FormMessage({
  message,
  id,
  error = false,
}: {
  message: string;
  id?: string;
  error?: boolean;
}) {
  return message ? (
    <p
      className={error ? "form-message form-error" : "form-message"}
      id={id}
      role={error ? "alert" : "status"}
      aria-live="polite"
    >
      {message}
    </p>
  ) : null;
}

function SignInPage({ client }: { client: IdentityClient }) {
  const mutation = useLogin(client);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  async function submit(event: FormEvent) {
    event.preventDefault();
    try {
      await mutation.mutateAsync({ email, password });
      navigate("/profile");
    } catch {
      // Keep server details out of the UI.
    }
  }
  return (
    <Page title="Sign in">
      <p className="identity-intro">Access your private Launchpad profile.</p>
      <form className="identity-form" onSubmit={submit}>
        <FormField
          id="signin-email"
          label="Email"
          type="email"
          value={email}
          onChange={setEmail}
          autoComplete="email"
          describedBy={mutation.isError ? "signin-error" : undefined}
          invalid={mutation.isError}
        />
        <FormField
          id="signin-password"
          label="Password"
          type="password"
          value={password}
          onChange={setPassword}
          autoComplete="current-password"
          describedBy={mutation.isError ? "signin-error" : undefined}
          invalid={mutation.isError}
        />
        <FormMessage
          id="signin-error"
          message={
            mutation.isError
              ? "We could not sign you in with those details."
              : ""
          }
          error
        />
        <button
          className="primary-button"
          disabled={mutation.isPending}
          type="submit"
        >
          {mutation.isPending ? "Signing in…" : "Sign in"}
        </button>
      </form>
      <nav className="identity-links" aria-label="Account actions">
        <a
          href="/register"
          onClick={(event) => {
            event.preventDefault();
            navigate("/register");
          }}
        >
          Create an account
        </a>
        <a
          href="/recover"
          onClick={(event) => {
            event.preventDefault();
            navigate("/recover");
          }}
        >
          Forgot your password?
        </a>
      </nav>
    </Page>
  );
}

function RegisterPage({ client }: { client: IdentityClient }) {
  const mutation = useRegister(client);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  async function submit(event: FormEvent) {
    event.preventDefault();
    try {
      await mutation.mutateAsync({ email, password });
    } catch {
      /* generic response below */
    }
  }
  return (
    <Page title="Create your account">
      <p className="identity-intro">
        Use at least 8 characters. Longer passphrases and spaces are welcome.
      </p>
      <form className="identity-form" onSubmit={submit}>
        <FormField
          id="register-email"
          label="Email"
          type="email"
          value={email}
          onChange={setEmail}
          autoComplete="email"
          describedBy={mutation.isError ? "register-error" : undefined}
          invalid={mutation.isError}
        />
        <FormField
          id="register-password"
          label="Password"
          type="password"
          value={password}
          onChange={setPassword}
          autoComplete="new-password"
          describedBy={mutation.isError ? "register-error" : undefined}
          invalid={mutation.isError}
        />
        <FormMessage
          id="register-error"
          message={
            mutation.isSuccess
              ? "If the address can receive Launchpad mail, we’ll send next steps shortly."
              : mutation.isError
                ? "We could not start registration. Please try again later."
                : ""
          }
          error={mutation.isError}
        />
        <button
          className="primary-button"
          disabled={mutation.isPending}
          type="submit"
        >
          {mutation.isPending ? "Creating…" : "Create account"}
        </button>
      </form>
      <BackToSignIn />
    </Page>
  );
}

function VerifyPage({ client }: { client: IdentityClient }) {
  const verify = useVerify(client);
  const resend = useRequestVerification(client);
  const [token] = useState(
    () => new URLSearchParams(window.location.search).get("token") ?? "",
  );
  useEffect(() => {
    if (token) window.history.replaceState({}, "", window.location.pathname);
  }, [token]);
  async function submit(event: FormEvent) {
    event.preventDefault();
    if (token) {
      try {
        await verify.mutateAsync({ token });
      } catch {
        // Render the safe mutation error below.
      }
    }
  }
  async function resendVerification() {
    try {
      await resend.mutateAsync();
    } catch {
      // Render the safe mutation error below.
    }
  }
  return (
    <Page title="Verify your email">
      <p className="identity-intro">
        Open the link from your email, then confirm here to activate
        verified-member access.
      </p>
      <form className="identity-form" onSubmit={submit}>
        <button
          className="primary-button"
          disabled={!token || verify.isPending}
          type="submit"
        >
          {verify.isPending ? "Verifying…" : "Confirm verification"}
        </button>
      </form>
      <FormMessage
        id="verify-error"
        message={
          verify.isSuccess
            ? "Your email is verified. You can now sign in."
            : verify.isError
              ? "That link is invalid or expired. Request a fresh link and try again."
              : ""
        }
        error={verify.isError}
      />
      <button
        className="secondary-button"
        disabled={resend.isPending}
        onClick={() => void resendVerification()}
        type="button"
      >
        {resend.isSuccess ? "A fresh link is on its way" : "Send a fresh link"}
      </button>
      <FormMessage
        message={
          resend.isError
            ? "We could not send a fresh link. Please try again later."
            : ""
        }
        error
      />
      <BackToSignIn />
    </Page>
  );
}

function RecoveryPage({ client }: { client: IdentityClient }) {
  const mutation = useRequestPasswordReset(client);
  const [email, setEmail] = useState("");
  async function submit(event: FormEvent) {
    event.preventDefault();
    try {
      await mutation.mutateAsync(email);
    } catch {
      /* retain generic copy */
    }
  }
  return (
    <Page title="Recover your account">
      <p className="identity-intro">
        Enter your email and we’ll send instructions if an account matches. We
        never reveal account existence.
      </p>
      <form className="identity-form" onSubmit={submit}>
        <FormField
          id="recover-email"
          label="Email"
          type="email"
          value={email}
          onChange={setEmail}
          autoComplete="email"
          describedBy={mutation.isError ? "recover-error" : undefined}
          invalid={mutation.isError}
        />
        <FormMessage
          id="recover-error"
          message={
            mutation.isSuccess
              ? "If the address matches an account, recovery instructions are on their way."
              : mutation.isError
                ? "We could not start recovery. Please try again later."
                : ""
          }
          error={mutation.isError}
        />
        <button
          className="primary-button"
          disabled={mutation.isPending}
          type="submit"
        >
          {mutation.isPending ? "Sending…" : "Send recovery email"}
        </button>
      </form>
      <BackToSignIn />
    </Page>
  );
}

function ResetPage({ client }: { client: IdentityClient }) {
  const mutation = useResetPassword(client);
  const [password, setPassword] = useState("");
  const [token] = useState(
    () => new URLSearchParams(window.location.search).get("token") ?? "",
  );
  useEffect(() => {
    if (token) window.history.replaceState({}, "", window.location.pathname);
  }, [token]);
  async function submit(event: FormEvent) {
    event.preventDefault();
    if (token) {
      try {
        await mutation.mutateAsync({ token, new_password: password });
        navigate("/signin");
      } catch {
        /* safe message below */
      }
    }
  }
  return (
    <Page title="Choose a new password">
      <p className="identity-intro">
        The link is used only when you explicitly confirm this form. Links
        expire after 60 minutes.
      </p>
      <form className="identity-form" onSubmit={submit}>
        <FormField
          id="reset-password"
          label="New password"
          type="password"
          value={password}
          onChange={setPassword}
          autoComplete="new-password"
          describedBy={mutation.isError ? "reset-error" : undefined}
          invalid={mutation.isError}
        />
        <FormMessage
          id="reset-error"
          message={
            mutation.isError
              ? "That recovery link is invalid, expired, or already used."
              : ""
          }
          error
        />
        <button
          className="primary-button"
          disabled={!token || mutation.isPending}
          type="submit"
        >
          {mutation.isPending ? "Updating…" : "Set new password"}
        </button>
      </form>
      <BackToSignIn />
    </Page>
  );
}

function PrivateProfileLanding({ client }: { client: IdentityClient }) {
  const logout = useLogout(client);
  const [error, setError] = useState(false);
  async function signOut() {
    setError(false);
    try {
      await logout.mutateAsync();
      navigate("/signin");
    } catch {
      setError(true);
    }
  }
  return (
    <Page title="Your private profile">
      <p className="identity-intro">
        You’re signed in. Profile editing will be available here.
      </p>
      <button
        className="secondary-button"
        disabled={logout.isPending}
        onClick={() => void signOut()}
        type="button"
      >
        {logout.isPending ? "Signing out…" : "Sign out"}
      </button>
      <FormMessage
        message={error ? "We could not sign you out. Please try again." : ""}
        error
      />
    </Page>
  );
}

function BackToSignIn() {
  return (
    <a
      className="back-link"
      href="/signin"
      onClick={(event) => {
        event.preventDefault();
        navigate("/signin");
      }}
    >
      Back to sign in
    </a>
  );
}

function FormField({
  id,
  label,
  type,
  value,
  onChange,
  autoComplete,
  describedBy,
  invalid = false,
}: {
  id: string;
  label: string;
  type: string;
  value: string;
  onChange: (value: string) => void;
  autoComplete: string;
  describedBy?: string;
  invalid?: boolean;
}) {
  return (
    <label className="form-field" htmlFor={id}>
      <span>{label}</span>
      <input
        autoComplete={autoComplete}
        aria-describedby={describedBy}
        aria-invalid={invalid || undefined}
        id={id}
        onChange={(event) => onChange(event.target.value)}
        required
        type={type}
        value={value}
      />
    </label>
  );
}
