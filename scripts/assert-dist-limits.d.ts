export const MAX_SITE_TOTAL_BYTES: number;
export const MAX_SINGLE_FILE_BYTES: number;

export function listFilesRecursive(dir: string): Promise<Array<{ path: string; size: number }>>;

export function checkDistLimits(
  webDistDir?: string,
  dataDistDir?: string,
): Promise<{
  valid: boolean;
  errors: string[];
  summary: string[];
}>;
