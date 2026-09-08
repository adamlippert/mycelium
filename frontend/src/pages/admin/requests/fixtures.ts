import type { AdminRequestRow } from '../../../api';

export const row = (over: Partial<AdminRequestRow>): AdminRequestRow => ({
  id: 1, imdb_id: 'tt1', tmdb_id: 1, title: 'Heat', media_type: 'movie', seasons: null, status: 'pending', note: null,
  created_at: '2026-09-01 10:00:00', reviewed_at: null, user_id: 3, username: 'adam', reviewer: null, library_status: null,
  ...over,
});
