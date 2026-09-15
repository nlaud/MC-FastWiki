export function extractAssetHrefs(html: string): string[];

export function smokeTest(
  targetUrl?: string,
  options?: {
    maxRetries?: number;
    retryDelayMs?: number;
  },
): Promise<{
  success: boolean;
  errors: string[];
  testedUrls: string[];
}>;
