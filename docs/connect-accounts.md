# Connect your accounts

All of these are optional. Everything else in WinAuto works without them.

## Gmail

WinAuto signs in to Gmail with an **app password**: a 16-letter code that only works for mail and that you can revoke at any time. Your real Google password is never used or stored.

1. Turn on **2-Step Verification** for your Google account at https://myaccount.google.com/security if it isn't on already (app passwords need it).
2. Go to **https://myaccount.google.com/apppasswords**, type `WinAuto` as the name and copy the 16-letter code.
3. In WinAuto open **Settings → Accounts**, enter your Gmail address, paste the code into **App password**, and press **Test Gmail**.
4. Optional: add a **Signature** for the end of your emails, and your name in **Settings → General** so drafts are signed properly.

The code is stored in **Windows Credential Manager** (search the Start menu for "Credential Manager" → Windows Credentials → `WinAuto`), never in WinAuto's own files. To revoke access, delete it on the Google page from step 2.

What you can do: send (always shown as an editable draft first), check unread, search (`emails from Sita`, `search my email for invoices`), read and reply.

> Google Workspace accounts (work or school) only work if your admin allows app passwords.

## WhatsApp

1. Install **WhatsApp Desktop** from the Microsoft Store and sign in.
2. In **Settings → Accounts**, set **Your country code** (e.g. `977` for Nepal, `91` for India, `1` for the US). It's added to numbers saved without one.
3. Save people as contacts (below), or send to a number directly: `whatsapp +977 9800000000: hi`.

When you send, WinAuto opens the chat with your message already typed, waits for your approval, then presses Enter in WhatsApp. If you'd rather press Enter yourself, turn off **Press Send in WhatsApp**.

Without WhatsApp Desktop, WinAuto opens WhatsApp Web in your browser instead, and you press Enter there.

## Discord

Discord doesn't allow bots to send messages from personal accounts, so WinAuto uses the Discord app the way you would: it opens Discord, uses the **Ctrl+K** quick switcher to find the person, types the message and presses Enter after you approve.

1. Install the Discord app and sign in.
2. Save each person's exact Discord username in their contact: `update contact Sita discord sita_k`.
3. Send with `discord Sita: are you on tonight?`.

Leave Discord alone for the few seconds it takes. If another window jumps in front, WinAuto won't press Enter. Turn off **Press Send in Discord** to always check before sending.

## Contacts

Email, WhatsApp and Discord find people in your WinAuto contacts:

- `add contact Ram Sharma ram@example.com +977 9800000000`
- `update contact Ram nickname bhai`
- `what's Sita's number` · `show my contacts` · `delete contact Ram`

**Import from Google Contacts:** at https://contacts.google.com choose **Export → Google CSV** (or vCard), then say `import contacts from C:\Users\you\Downloads\contacts.csv`. Importing again updates existing people instead of duplicating them.

## Calendar

WinAuto reads your calendar through its **private iCal link**: read-only, no sign-in, nothing to install.

- **Google Calendar:** on the web, open **Settings**, click your calendar on the left, scroll to **Secret address in iCal format** and copy it.
- **Outlook / Microsoft 365:** **Settings → Calendar → Shared calendars → Publish a calendar**, choose the calendar and "Can view all details", then copy the **ICS** link.
- **Apple iCloud:** in the Calendar app, share the calendar as a **Public Calendar** and copy the link (`webcal://` links work).

Paste the link into **Settings → Accounts → Calendar links** (one per line, several calendars are fine).

Then ask `what's on my calendar tomorrow` or `what's my next meeting`. Your next meeting also shows on the home screen and in the morning briefing.

Events you add with WinAuto (`add dentist friday 3pm to my calendar`) are kept locally and get a reminder 10 minutes before. They aren't added to Google or Outlook, since the link is read-only.

> Treat the private link like a password: anyone who has it can see your calendar. If it leaks, reset it on the same settings page.
