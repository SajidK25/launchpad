import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import type { ProfileClient, ProfilePatch } from "./client";

export const profileKeys = {
  viewer: ["profiles", "viewer"] as const,
  public: (accountId: string) => ["profiles", "public", accountId] as const,
  photo: (accountId: string) => ["profiles", "photo", accountId] as const,
};

export function useViewerProfile(client: ProfileClient) {
  return useQuery({
    queryKey: profileKeys.viewer,
    queryFn: client.fetchViewerProfile,
  });
}

export function usePublicProfile(client: ProfileClient, accountId: string) {
  return useQuery({
    queryKey: profileKeys.public(accountId),
    queryFn: () => client.fetchPublicProfile(accountId),
    enabled: accountId.length > 0,
  });
}

function useProfileMutation<T>(
  client: ProfileClient,
  mutationFn: (value: T) => Promise<unknown>,
) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: profileKeys.viewer });
      void queryClient.invalidateQueries({ queryKey: ["profiles", "public"] });
      queryClient.removeQueries({ queryKey: ["profiles", "photo"] });
    },
  });
}

export function useCreatePhotoUpload(client: ProfileClient) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: client.createPhotoUpload,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: profileKeys.viewer });
    },
  });
}

export function useCompletePhotoUpload(client: ProfileClient) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: client.completePhotoUpload,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: profileKeys.viewer });
      queryClient.removeQueries({ queryKey: ["profiles", "photo"] });
    },
  });
}

export function useProfilePhoto(client: ProfileClient, accountId: string) {
  return useQuery({
    queryKey: profileKeys.photo(accountId),
    queryFn: () => client.fetchPhoto(accountId),
    enabled: accountId.length > 0,
  });
}

export function useUpdateProfile(client: ProfileClient) {
  return useProfileMutation<ProfilePatch>(client, client.updateProfile);
}

export function usePublishProfile(client: ProfileClient) {
  return useProfileMutation<number>(client, client.publishProfile);
}

export function useUnpublishProfile(client: ProfileClient) {
  return useProfileMutation<number>(client, client.unpublishProfile);
}
