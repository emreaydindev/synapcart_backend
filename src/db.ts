/** Row types for the D1 schema in migrations/ and the queries shared across routes. */

export interface UserRow {
  id: string;
  email: string;
  hashed_password: string;
  full_name: string | null;
  language: string;
  currency: string;
  token_version: number;
  created_at: string;
  plan: string;
  plan_expires_at: string | null;
  plan_source: string | null;
  play_purchase_token: string | null;
  play_product_id: string | null;
  apple_original_transaction_id: string | null;
  apple_product_id: string | null;
  reset_token: string | null;
  reset_token_expires: string | null;
  delete_token: string | null;
  delete_token_expires: string | null;
}

export interface SessionRow {
  id: number;
  user_id: string;
  title: string | null;
  created_at: string;
}

export interface MessageRow {
  id: number;
  session_id: number;
  role: string;
  content: string;
  products: string | null;
  created_at: string;
}

export interface FavoriteRow {
  id: number;
  user_id: string;
  title: string;
  price: number | null;
  currency: string | null;
  source: string | null;
  link: string;
  thumbnail: string | null;
  created_at: string;
  target_price: number | null;
  last_checked_price: number | null;
  last_checked_at: string | null;
  last_notified_price: number | null;
}

export interface DeviceTokenRow {
  id: number;
  user_id: string;
  token: string;
  platform: string | null;
  created_at: string;
  updated_at: string;
}

export const getUserByEmail = (db: D1Database, email: string) =>
  db.prepare("SELECT * FROM users WHERE email = ? COLLATE NOCASE").bind(email.trim().toLowerCase()).first<UserRow>();

export const getUserById = (db: D1Database, id: string) =>
  db.prepare("SELECT * FROM users WHERE id = ?").bind(id).first<UserRow>();

/** Updates the given columns of a user and returns the fresh row. */
export async function updateUser(db: D1Database, id: string, fields: Partial<UserRow>): Promise<UserRow> {
  const keys = Object.keys(fields) as (keyof UserRow)[];
  if (keys.length) {
    const sql = `UPDATE users SET ${keys.map((k) => `${k} = ?`).join(", ")} WHERE id = ?`;
    await db
      .prepare(sql)
      .bind(...keys.map((k) => fields[k] ?? null), id)
      .run();
  }
  return (await getUserById(db, id))!;
}

export const deleteUser = (db: D1Database, id: string) => db.prepare("DELETE FROM users WHERE id = ?").bind(id).run();
