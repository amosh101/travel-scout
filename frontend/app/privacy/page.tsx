export const metadata = {
  title: "Privacy Policy — Travel Scout",
};

export default function PrivacyPage() {
  return (
    <main className="container max-w-3xl py-12 text-foreground">
      <h1 className="text-3xl font-semibold">Privacy Policy</h1>
      <p className="mt-1 text-sm text-muted-foreground">
        Effective 2026-10-21 · Travel Scout (subscriptions + booking concierge)
      </p>

      <div className="mt-8 space-y-6 text-sm leading-6">
        <section>
          <h2 className="text-lg font-semibold">What we collect</h2>
          <ul className="mt-2 list-disc space-y-1 pl-5">
            <li><strong>Account:</strong> email, name, password (bcrypt-hashed), subscription tier, Stripe customer reference. Phone number is optional, collected so confirmations can reach you by SMS.</li>
            <li><strong>Travel profile:</strong> interests, home airport/origin, optional nationality, passport expiry and issue country, date of birth, emergency contact. Passport NUMBERS are stored obfuscated; agents receive your passport expiry and dates when you hand them a booking.</li>
            <li><strong>Chats:</strong> messages and attachments you exchange with booking agents per trip (threads keep full history so any agent can service your booking).</li>
            <li><strong>Bookings:</strong> when you hand a trip to an agent, the queue keeps dates, your hand-off note, the recorded payment (amount/currency/method note), the booking reference, and outcome notes — the financial record for the booking.</li>
            <li><strong>Usage:</strong> audit records of logins, searches, saves, hand-offs, and admin actions (who did what, when — for security and support).</li>
          </ul>
        </section>

        <section>
          <h2 className="text-lg font-semibold">What we never do</h2>
          <ul className="mt-2 list-disc space-y-1 pl-5">
            <li>We never sell personal data. Emails and SMS go only to you, about your trips, confirmations, and your weekly digest.</li>
            <li>The weekly digest email uses the same discovery engine as the site — derived from your interests and origin, nothing else.</li>
            <li>Card details never touch this service — subscription payments run on Stripe&apos;s hosted checkout; agent payments are handled directly with your agent off-platform and recorded in the app.</li>
          </ul>
        </section>

        <section>
          <h2 className="text-lg font-semibold">Your rights (GDPR / Art. 15–20)</h2>
          <ul className="mt-2 list-disc space-y-1 pl-5">
            <li><strong>Access:</strong> download everything your account holds at <code>/api/me/export</code> (profile, interests, trips, bookings, your audit trail).</li>
            <li><strong>Erasure:</strong> delete your account any time (in settings/account pages, or <code>DELETE /api/me</code> with confirm). Your PII is blanked or replaced by a tombstone; you can never log in again. We keep the financial record rows (bookings and audit) as required for tax and dispute handling, but they reference an account that no longer identifies you. Your Stripe customer record is deleted on our side too.</li>
            <li><strong>Opt-out:</strong> stop the weekly digest any time in your profile (digest switch) — confirmations still arrive because they are transactional.</li>
          </ul>
        </section>

        <section>
          <h2 className="text-lg font-semibold">Retention</h2>
          <p className="mt-2">
            Account data lives while your account is active. Booking and
            payment records live as long as the financial records are needed.
            Audit records are append-only for security. Deactivated (erased)
            accounts keep no personal profile data.
          </p>
        </section>

        <section>
          <h2 className="text-lg font-semibold">Contact</h2>
          <p className="mt-2">
            Data-protection questions and requests: open a GitHub issue on the
            project repository, or reach your booking agent in chat. Erasure
            and export requests via <code>DELETE /api/me</code> and{" "}
            <code>GET /api/me/export</code> are self-service and immediate.
          </p>
        </section>
      </div>
    </main>
  );
}