/** Generated from schema.graphql and operations.graphql. Do not edit by hand. */

export type Scalars = {
  UUID: string;
  String: string;
  Boolean: boolean;
  Date: string;
  DateTime: string;
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
  publicProfile: {
    accountId: string;
    displayName: string;
    bio: string;
    links: Array<string>;
    photoUrl: string | null;
  } | null;
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
  viewerProfile: {
    accountId: string;
    displayName: string;
    bio: string;
    links: Array<string>;
    photoUrl: string | null;
    visibility: string;
    version: number;
  };
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

export type ViewerProductsQueryVariables = {
  first?: number;
  after?: string | null;
};

export type ViewerProductsQuery = {
  viewerProducts: {
    items: Array<{
      id: string;
      status: string;
      version: number;
      name: string | null;
      pitch: string | null;
      createdAt: string;
      updatedAt: string;
    }>;
    nextCursor: string | null;
  };
};

export const VIEWER_PRODUCTS_QUERY =
  `query ViewerProducts($first: Int! = 20, $after: String) {
  viewerProducts(first: $first, after: $after) {
    items {
      id
      status
      version
      name
      pitch
      createdAt
      updatedAt
    }
    nextCursor
  }
}` as const;

export type ViewerProductQueryVariables = {
  id: string;
};

export type ViewerProductQuery = {
  viewerProduct: {
    summary: {
      id: string;
      status: string;
      version: number;
      name: string | null;
      pitch: string | null;
      createdAt: string;
      updatedAt: string;
    };
    description: string | null;
    websiteUrl: string | null;
    topics: Array<{
      id: string;
      displayName: string;
      position: number;
    }>;
    assets: Array<{
      id: string;
      kind: string;
      mediaType: string;
      byteCount: number;
      url: string;
    }>;
    submission: {
      id: string;
      submittedAt: string;
      productVersion: number;
    } | null;
    reviewOutcome: {
      status: string;
      feedback: string | null;
    } | null;
  } | null;
};

export const VIEWER_PRODUCT_QUERY = `query ViewerProduct($id: UUID!) {
  viewerProduct(id: $id) {
    summary {
      id
      status
      version
      name
      pitch
      createdAt
      updatedAt
    }
    description
    websiteUrl
    topics {
      id
      displayName
      position
    }
    assets {
      id
      kind
      mediaType
      byteCount
      url
    }
    submission {
      id
      submittedAt
      productVersion
    }
    reviewOutcome {
      status
      feedback
    }
  }
}` as const;

export type ReviewQueueQueryVariables = {
  first?: number;
  after?: string | null;
};

export type ReviewQueueQuery = {
  reviewQueue: {
    items: Array<{
      product: {
        id: string;
        status: string;
        version: number;
        name: string | null;
        pitch: string | null;
        createdAt: string;
        updatedAt: string;
      };
      submission: {
        id: string;
        submittedAt: string;
        productVersion: number;
      };
      possibleDuplicate: boolean;
      founderSuspended: boolean;
    }>;
    nextCursor: string | null;
  };
};

export const REVIEW_QUEUE_QUERY =
  `query ReviewQueue($first: Int! = 20, $after: String) {
  reviewQueue(first: $first, after: $after) {
    items {
      product {
        id
        status
        version
        name
        pitch
        createdAt
        updatedAt
      }
      submission {
        id
        submittedAt
        productVersion
      }
      possibleDuplicate
      founderSuspended
    }
    nextCursor
  }
}` as const;

export type ReviewProductQueryVariables = {
  id: string;
};

export type ReviewProductQuery = {
  reviewProduct: {
    product: {
      summary: {
        id: string;
        status: string;
        version: number;
        name: string | null;
        pitch: string | null;
        createdAt: string;
        updatedAt: string;
      };
      description: string | null;
      websiteUrl: string | null;
      topics: Array<{
        id: string;
        displayName: string;
        position: number;
      }>;
      assets: Array<{
        id: string;
        kind: string;
        mediaType: string;
        byteCount: number;
        url: string;
      }>;
      submission: {
        id: string;
        submittedAt: string;
        productVersion: number;
      } | null;
    };
    submission: {
      id: string;
      submittedAt: string;
      productVersion: number;
    };
    possibleDuplicate: boolean;
    founderSuspended: boolean;
  } | null;
};

export const REVIEW_PRODUCT_QUERY = `query ReviewProduct($id: UUID!) {
  reviewProduct(id: $id) {
    product {
      summary {
        id
        status
        version
        name
        pitch
        createdAt
        updatedAt
      }
      description
      websiteUrl
      topics {
        id
        displayName
        position
      }
      assets {
        id
        kind
        mediaType
        byteCount
        url
      }
      submission {
        id
        submittedAt
        productVersion
      }
    }
    submission {
      id
      submittedAt
      productVersion
    }
    possibleDuplicate
    founderSuspended
  }
}` as const;

export type ApprovedReviewsQueryVariables = {
  first?: number;
  after?: string | null;
};

export type ApprovedReviewsQuery = {
  approvedReviews: {
    items: Array<{
      product: {
        id: string;
        status: string;
        version: number;
        name: string | null;
        pitch: string | null;
        createdAt: string;
        updatedAt: string;
      };
      submission: {
        id: string;
        submittedAt: string;
        productVersion: number;
      };
      approvedAt: string;
    }>;
    nextCursor: string | null;
  };
};

export const APPROVED_REVIEWS_QUERY =
  `query ApprovedReviews($first: Int! = 20, $after: String) {
  approvedReviews(first: $first, after: $after) {
    items {
      product {
        id
        status
        version
        name
        pitch
        createdAt
        updatedAt
      }
      submission {
        id
        submittedAt
        productVersion
      }
      approvedAt
    }
    nextCursor
  }
}` as const;

export type ViewerNotificationInboxQueryVariables = {
  first?: number;
  after?: string | null;
};

export type ViewerNotificationInboxQuery = {
  viewerNotificationInbox: {
    items: Array<{
      id: string;
      productId: string;
      kind: "REVIEW_APPROVED" | "REVIEW_REJECTED" | "REVIEW_CHANGES_REQUESTED";
      createdAt: string;
      readAt: string | null;
    }>;
    unreadCount: number;
    nextCursor: string | null;
  };
};

export const VIEWER_NOTIFICATION_INBOX_QUERY =
  `query ViewerNotificationInbox($first: Int! = 20, $after: String) {
  viewerNotificationInbox(first: $first, after: $after) {
    items {
      id
      productId
      kind
      createdAt
      readAt
    }
    unreadCount
    nextCursor
  }
}` as const;

export type ViewerLaunchBookingsQueryVariables = {
  first?: number;
  after?: string | null;
};

export type ViewerLaunchBookingsQuery = {
  viewerLaunchBookings: {
    items: Array<{
      id: string;
      productId: string;
      state: string;
      productStatus: string;
      launchAt: string;
      failureReason: string | null;
      createdAt: string;
      closedAt: string | null;
    }>;
    nextCursor: string | null;
  };
};

export const VIEWER_LAUNCH_BOOKINGS_QUERY =
  `query ViewerLaunchBookings($first: Int! = 20, $after: String) {
  viewerLaunchBookings(first: $first, after: $after) {
    items {
      id
      productId
      state
      productStatus
      launchAt
      failureReason
      createdAt
      closedAt
    }
    nextCursor
  }
}` as const;

export type ViewerLaunchNotificationPreferencesQueryVariables = {};

export type ViewerLaunchNotificationPreferencesQuery = {
  viewerLaunchNotificationPreferences: {
    reminderEmail: boolean;
    reminderInSite: boolean;
    liveEmail: boolean;
    liveInSite: boolean;
    failureEmail: boolean;
    failureInSite: boolean;
  };
};

export const VIEWER_LAUNCH_NOTIFICATION_PREFERENCES_QUERY =
  `query ViewerLaunchNotificationPreferences {
  viewerLaunchNotificationPreferences {
    reminderEmail
    reminderInSite
    liveEmail
    liveInSite
    failureEmail
    failureInSite
  }
}` as const;

export type PublicProductQueryVariables = {
  id: string;
};

export type PublicProductQuery = {
  publicProduct: {
    id: string;
    name: string;
    pitch: string;
    description: string;
    websiteUrl: string;
    launchedAt: string;
    logo: {
      id: string;
      kind: string;
      mediaType: string;
      byteCount: number;
      url: string;
    } | null;
    screenshots: Array<{
      id: string;
      kind: string;
      mediaType: string;
      byteCount: number;
      url: string;
    }>;
    topics: Array<string>;
  } | null;
};

export const PUBLIC_PRODUCT_QUERY = `query PublicProduct($id: UUID!) {
  publicProduct(id: $id) {
    id
    name
    pitch
    description
    websiteUrl
    launchedAt
    logo {
      id
      kind
      mediaType
      byteCount
      url
    }
    screenshots {
      id
      kind
      mediaType
      byteCount
      url
    }
    topics
  }
}` as const;

export type PublicLaunchesQueryVariables = {
  date?: string | null;
  first?: number;
  after?: string | null;
};

export type PublicLaunchesQuery = {
  publicLaunches: {
    todayDate: string;
    selectedDate: string;
    items: Array<{
      id: string;
      name: string;
      pitch: string;
      logoUrl: string | null;
      topics: Array<string>;
    }>;
    nextCursor: string | null;
  };
};

export const PUBLIC_LAUNCHES_QUERY =
  `query PublicLaunches($date: Date, $first: Int! = 20, $after: String) {
  publicLaunches(date: $date, first: $first, after: $after) {
    todayDate
    selectedDate
    items {
      id
      name
      pitch
      logoUrl
      topics
    }
    nextCursor
  }
}` as const;

export type TopicChoicesQueryVariables = {
  first?: number;
  query?: string | null;
};

export type TopicChoicesQuery = {
  topicChoices: Array<{
    id: string;
    displayName: string;
  }>;
};

export const TOPIC_CHOICES_QUERY =
  `query TopicChoices($first: Int! = 20, $query: String) {
  topicChoices(first: $first, query: $query) {
    id
    displayName
  }
}` as const;

export type PublicProductCatalogQueryVariables = {
  search?: string | null;
  topicIds?: Array<string> | null;
  first?: number;
  after?: string | null;
};

export type PublicProductCatalogQuery = {
  publicProductCatalog: {
    items: Array<{
      id: string;
      name: string;
      pitch: string;
      logoUrl: string | null;
      topics: Array<string>;
    }>;
    nextCursor: string | null;
  };
};

export const PUBLIC_PRODUCT_CATALOG_QUERY =
  `query PublicProductCatalog($search: String, $topicIds: [UUID!] = [], $first: Int! = 20, $after: String) {
  publicProductCatalog(
    search: $search
    topicIds: $topicIds
    first: $first
    after: $after
  ) {
    items {
      id
      name
      pitch
      logoUrl
      topics
    }
    nextCursor
  }
}` as const;

export type PublicCatalogTopicsQueryVariables = {
  query?: string | null;
  selectedIds?: Array<string> | null;
  first?: number;
};

export type PublicCatalogTopicsQuery = {
  publicCatalogTopics: {
    choices: Array<{
      id: string;
      displayName: string;
    }>;
    selected: Array<{
      id: string;
      displayName: string;
    }>;
  };
};

export const PUBLIC_CATALOG_TOPICS_QUERY =
  `query PublicCatalogTopics($query: String, $selectedIds: [UUID!] = [], $first: Int! = 20) {
  publicCatalogTopics(query: $query, selectedIds: $selectedIds, first: $first) {
    choices {
      id
      displayName
    }
    selected {
      id
      displayName
    }
  }
}` as const;
