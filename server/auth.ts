// Who is making this request? Every route asks this one function, and every row in the database is
// scoped to the id it returns.
//
// For now there are no accounts: the server is meant to run for one person (on your own machine, or
// behind something that already restricts access), so everyone is "local". To host it for many people,
// replace this with a real check (a session cookie, an OAuth token, a reverse proxy's auth header…) and
// return that user's id, or null to answer 401.
import type { IncomingMessage } from "node:http";

export function currentUser(_req: IncomingMessage): string | null {
  return "local";
}
