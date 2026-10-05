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
      kind: unknown;
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
      kind
      createdAt
      readAt
    }
    unreadCount
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
