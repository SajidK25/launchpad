/** Generated from schema.graphql and operations.graphql. Do not edit by hand. */

export type Scalars = {
  UUID: string;
  String: string;
  Boolean: boolean;
  Int: number;
};

export type PublicProfile = {
  accountId: string;
  displayName: string;
  bio: string;
  links: Array<string>;
  photoUrl: string | null;
};

export type ViewerProfile = {
  accountId: string;
  displayName: string;
  bio: string;
  links: Array<string>;
  photoUrl: string | null;
  visibility: string;
  version: number;
};

export type PublicProfileQueryVariables = {
  accountId: string;
};

export type PublicProfileQuery = {
  publicProfile: PublicProfile | null;
};

export const PUBLIC_PROFILE_QUERY = `query PublicProfile($accountId: UUID!) {
  publicProfile(accountId: $accountId) {
    accountId
    displayName
    bio
    links
    photoUrl
  }
}` as const;

export type ViewerProfileQueryVariables = {};

export type ViewerProfileQuery = {
  viewerProfile: ViewerProfile;
};

export const VIEWER_PROFILE_QUERY = `query ViewerProfile {
  viewerProfile {
    accountId
    displayName
    bio
    links
    photoUrl
    visibility
    version
  }
}` as const;
