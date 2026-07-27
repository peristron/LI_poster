li_poster

li_poster is a self-contained Streamlit application that prepares, reviews,schedules, and publishes short Latin-first posts to a connected LinkedIn memberprofile.

Each post uses this format:

Latin text

English translation

— attribution

The application includes:

a curated secular sayings library;

CSV import and export;

DeepSeek-assisted generation, translation, metadata backfill, and review;

human approval controls;

randomized scheduling;

LinkedIn OAuth 2.0 authentication and member posting;

encrypted LinkedIn-token storage;

GitHub-backed runtime state;

dry-run, pause, queue-review, and uncertain-result safeguards; and

a collapsed in-app usage and troubleshooting guide.

This is an independent personal project. It is not affiliated with, endorsedby, or operated by LinkedIn, Microsoft, DeepSeek, GitHub, Streamlit, or theauthor's employer.

Current scope

The current application publishes Latin-first sayings. Its LinkedIn connection,queue, scheduling, persistence, and review architecture could later supportother post types, but general-purpose LinkedIn content is not yet implemented.

Quick reference

Item

Current value

Main application file

streamlit_app.py

Supported Python version

Python 3.12

Streamlit URL used during setup

https://liposter.streamlit.app/

Runtime-state branch

runtime-state

Runtime-state file

runtime/state.json

LinkedIn authorization scopes

openid profile w_member_social

Default DeepSeek model

deepseek-v4-flash

Background worker interval

approximately 45 seconds while awake

Default timezone

America/Toronto

Recommended initial mode

automation paused and dry-run on

Repository files

The minimal deployment needs:

streamlit_app.py
requirements.txt
README.md

requirements.txt:

streamlit==1.47.1
pandas==2.3.1
requests==2.32.4
cryptography==45.0.5

The application creates and maintains its runtime state through the GitHub API.No database or additional state file needs to be committed to the main branch.

How the application works

administrator
    |
    v
Streamlit interface
    |
    +--> sayings library and DeepSeek review workflow
    |
    +--> randomized schedule and posting queue
    |
    +--> LinkedIn OAuth and member-post API
    |
    +--> GitHub runtime-state branch

The deployed Streamlit process starts a background worker. Approximately every45 seconds, while the process is awake, the worker:

loads the latest state from GitHub;

confirms that automation is enabled and dry-run is off;

confirms that LinkedIn is connected and the token has not expired;

finds the next due queued item;

claims the item so a second worker cannot post it simultaneously;

confirms that the underlying saying remains approved;

publishes the post through LinkedIn;

records the result; and

replenishes the randomized schedule when appropriate.

Streamlit Community Cloud is not a guaranteed always-on task scheduler. Anexternal app-waker can reduce hibernation, but posting times should still betreated as approximate.

Prerequisites

Before deployment, prepare:

a GitHub account and repository;

a Streamlit Community Cloud account connected to GitHub;

a LinkedIn member account;

a LinkedIn Page that you own or are authorized to use for developer-appassociation;

a LinkedIn developer application;

the LinkedIn Share on LinkedIn product;

the LinkedIn Sign In with LinkedIn using OpenID Connect product;

a fine-grained GitHub personal access token;

an application administrator password;

a Fernet encryption key; and

optionally, a DeepSeek API key.

1. Create the GitHub repository

Create a repository, such as LI_poster.

Upload the application as streamlit_app.py.

Upload requirements.txt.

Add this README.md.

Keep credentials out of every branch and committed file.

Repository privacy

The application writes runtime information to a runtime-state branch. Thatstate includes:

sayings and AI candidates;

schedule settings and queued posts;

posting history and application events;

the LinkedIn display name;

temporary OAuth state; and

the LinkedIn access token encrypted with the Fernet key.

If the repository is public, the runtime-state branch and its non-secretmetadata are also public. The LinkedIn token remains encrypted, but a privaterepository is preferable when the connected Streamlit plan supports it.

2. Create the GitHub state token

Create a fine-grained GitHub personal access token:

Open GitHub Settings.

Open Developer settings.

Open Personal access tokens.

Select Fine-grained tokens.

Select Generate new token.

Give it a descriptive name, such as li_poster Streamlit state.

Select an appropriate expiration date.

Set the resource owner to your GitHub account.

Select Only select repositories.

Select only the LI_poster repository.

Under repository permissions, set Contents to Read and write.

Leave the required Metadata permission as Read-only.

Generate the token.

Copy it immediately and store it securely.

This token becomes GITHUB_STATE_TOKEN in Streamlit Secrets.

The application uses the token to:

inspect the repository's default branch;

create runtime-state if it does not exist;

create runtime/state.json; and

read and update the runtime state.

3. Create the LinkedIn Page

LinkedIn requires a Page association when creating a developer application.This Page is not necessarily the destination for posts.

For this application:

the developer application is associated with a Page;

OAuth connects an individual LinkedIn member; and

posts are published to that connected member's profile.

Do not associate an employer's Page unless you are authorized to do so.

If LinkedIn offers a default Page for individual developers, it can be used.Alternatively, create a small Page that accurately represents the personalproject:

Open LinkedIn's Page-creation workflow.

Enter a project name, such as li_poster.

Choose a unique Page URL.

Add a valid website URL if required.

Choose an accurate industry.

Use the smallest accurate organization size.

Choose an accurate organization type, such as Self-employed, whenappropriate.

Add a logo and short description.

Confirm that you are authorized to create and manage the Page.

Create the Page.

If a newly created Page is not immediately visible in the developer-app form,wait briefly, reload the form, search by Page name, and try the complete PageURL. If LinkedIn removes or makes the Page unavailable, recreate or restore itbefore continuing.

4. Create the LinkedIn developer application

Open the LinkedIn Developer portal.

Open My apps.

Select Create app.

Enter the application name, such as li_poster.

Select the project Page created or authorized in the previous step.

Provide a stable, publicly accessible privacy-policy URL.

Upload a square application logo.

Read and accept the LinkedIn API terms.

Select Create app.

The selected LinkedIn Page cannot normally be changed after the application iscreated. Confirm the Page before saving.

5. Add the LinkedIn products

Open the developer application's Products tab.

Request and confirm access to:

Share on LinkedIn

Sign In with LinkedIn using OpenID Connect

The Share on LinkedIn product supplies member-posting access. OpenID Connectsupplies member identity and sign-in scopes.

The application requests:

openid profile w_member_social

Additional advertising, community-management, organization, events, lead-sync,or portability APIs are not required for the current member-posting workflow.

6. Configure LinkedIn OAuth

Open the developer application's Auth tab.

Copy the credentials

Copy:

Client ID

Primary Client Secret

These become:

LINKEDIN_CLIENT_ID = "..."
LINKEDIN_CLIENT_SECRET = "..."

Never put the client secret in GitHub.

Add the redirect URI

Under Authorized redirect URLs for your app, add the exact deployedStreamlit URL:

https://liposter.streamlit.app/

The value must exactly match LINKEDIN_REDIRECT_URI in Streamlit Secrets.Scheme, hostname, path, and trailing slash must match.

For example, these may be treated as different:

https://liposter.streamlit.app
https://liposter.streamlit.app/

Use the exact form configured in both locations.

7. Generate the application secrets

Administrator password

Use a long, unique password. To generate a random value in Windows PowerShell:

$b = New-Object byte[] 32; $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create(); $rng.GetBytes($b); $rng.Dispose(); [Convert]::ToBase64String($b)

Fernet key

The Fernet key must be a URL-safe Base64 encoding of exactly 32 random bytes.In Windows PowerShell:

$b = New-Object byte[] 32; $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create(); $rng.GetBytes($b); $rng.Dispose(); ([Convert]::ToBase64String($b)).Replace('+','-').Replace('/','_')

Or, in a Python environment containing cryptography:

python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

Preserve the Fernet key. The stored LinkedIn token cannot be decrypted if thekey is lost or replaced. If the key must be replaced, reconnect LinkedIn so thenew token is encrypted with the new key.

8. Deploy to Streamlit Community Cloud

Sign in to Streamlit Community Cloud.

Select Create app.

Select the GitHub repository.

Select the main branch.

Set the main file to streamlit_app.py.

Deploy the application.

Open App settings.

Under General, select Python 3.12.

Confirm the desired app URL, such as liposter.streamlit.app.

Open Secrets.

Add the TOML configuration shown below.

Save the settings.

Allow the application to restart.

9. Configure Streamlit Secrets

Use placeholders rather than committing real values:

ADMIN_PASSWORD = "PASTE_A_LONG_RANDOM_PASSWORD"

GITHUB_REPOSITORY = "YOUR_GITHUB_USERNAME/LI_poster"
GITHUB_STATE_TOKEN = "github_pat_PASTE_TOKEN"

LINKEDIN_CLIENT_ID = "PASTE_LINKEDIN_CLIENT_ID"
LINKEDIN_CLIENT_SECRET = "PASTE_LINKEDIN_CLIENT_SECRET"
LINKEDIN_REDIRECT_URI = "https://liposter.streamlit.app/"

FERNET_KEY = "PASTE_URL_SAFE_FERNET_KEY"
TIMEZONE = "America/Toronto"

DEEPSEEK_API_KEY = "PASTE_DEEPSEEK_API_KEY"
DEEPSEEK_MODEL = "deepseek-v4-flash"

Required secrets:

ADMIN_PASSWORD

GITHUB_REPOSITORY

GITHUB_STATE_TOKEN

LINKEDIN_CLIENT_ID

LINKEDIN_CLIENT_SECRET

LINKEDIN_REDIRECT_URI

FERNET_KEY

Recommended:

TIMEZONE

Optional:

DEEPSEEK_API_KEY

DEEPSEEK_MODEL

Without the DeepSeek key, LinkedIn, scheduling, CSV, and manual sayings featurescontinue to work. Only the AI workshop is disabled.

10. Connect the LinkedIn member account

Open the deployed application.

Sign in with ADMIN_PASSWORD.

Open LinkedIn and setup.

Select Prepare LinkedIn connection.

Select Continue to LinkedIn.

Review the requested permissions.

Authorize the developer application.

Allow LinkedIn to redirect back to Streamlit.

Confirm that the application displays Connected as [member name].

Confirm that the configuration table shows the GitHub repository,LinkedIn application, HTTPS redirect URI, and encryption key as ready.

The LinkedIn authorization link contains a random state value and expires afterapproximately ten minutes. Prepare a new connection if the link expires.

11. Add the application to the app-waker

If an external app-waker is already used, add:

https://liposter.streamlit.app

to its active URL list.

The waker should visit the app regularly enough to reduce hibernation. It doesnot provide a posting-time guarantee. Streamlit may still restart, reprovision,or temporarily delay the worker.

First-time validation workflow

Keep the application safe while validating the complete setup:

Confirm the Dashboard shows LinkedIn: Connected.

Confirm Automation: Paused.

Confirm Dry-run mode is on.

Open Sayings.

Review several bundled sayings.

Approve only sayings that have been independently checked.

Select Save sayings.

Open Schedule.

Save conservative schedule settings.

Select Fill randomized schedule.

Inspect every queued post on the Dashboard.

Optionally publish one connections-only test from LinkedIn and setup.

Verify the post directly on LinkedIn.

Keep automation paused until the queue, visibility, and post formatting areconfirmed.

The connections-only test is a real immediate LinkedIn post. It bypassesdry-run mode and requires explicit confirmation in the interface.

Using the sayings library

Open Sayings to review and edit:

approval status;

Latin text;

English translation;

attribution;

Latin classification;

primary theme;

source language;

source period;

source confidence;

source text;

origin;

verification status; and

internal notes.

Only approved entries can be scheduled.

Internal notes, verification status, AI assessments, source confidence, andduplicate warnings are not included in LinkedIn posts.

Secular wording policy

The application scans publishable or source-supporting fields:

Latin;

English translation;

attribution; and

original source text.

It does not scan internal notes.

When excluded religious or theological wording is detected:

newly generated candidates are rejected;

older staged candidates are marked reject;

library entries are unapproved and blocked by the policy; and

the warning identifies the exact field and matched wording.

The filter is intentionally conservative. Human review remains necessary.

Importing and exporting CSV

Export

Select Download sayings CSV to obtain the complete current library.

Import

Expand Import sayings from CSV.

Upload a UTF-8 CSV.

Confirm the required columns:

latin
translation
attribution

Optionally include the other exported fields.

Select Import CSV as unapproved.

Review all imported rows.

Imported entries are always unapproved. Exact and near duplicates are skipped.Content conflicting with the secular wording policy is blocked.

Using the DeepSeek AI workshop

DeepSeek is editorial assistance, not independent source verification.

Generated or translated content:

is staged separately;

is never automatically approved;

is never automatically scheduled;

is never automatically published; and

requires human review before entering the library.

Each DeepSeek request uses the configured API account and may incur usagecharges.

Suggest sayings

Configure:

number of candidates;

required primary theme, if any;

optional supporting themes;

source-language mode;

required source language, when applicable; and

preferred source languages.

Source-language modes

One required source language

Every result must originate in the required language. To guarantee Arabicsources:

Source-language mode: One required source language
Required source language: Arabic

Balanced coverage across preferred languages

At least one candidate must come from every preferred language. The candidatecount must be at least the number of listed languages.

Example:

Number of candidates: 4
Preferred source languages: Latin, Ancient Greek, Classical Chinese, Arabic
Source-language mode: Balanced coverage across preferred languages

Preferred languages only

The listed languages guide DeepSeek but do not guarantee coverage.

Classical Arabic sources

Classical Arabic intellectual material is often medieval rather than ancient.The application permits secular pre-modern Arabic sources through 1500 CE,especially material associated with:

mathematics;

medicine;

optics;

observation;

natural philosophy;

ethics; and

learning.

Arabic-source material is labelled as a modern Latin rendering from Arabic. Itmust not be labelled as original Latin.

Replacement behavior

Generation uses up to three rounds:

request the desired candidates;

validate each result locally;

request replacements for filtered, duplicate, off-theme, wrong-language, ormissing results; and

stage a valid partial result with a warning if the requested total stillcannot be reached.

A DeepSeek response that is truncated, empty, or malformed is retried once witha larger output allowance. Model thinking is disabled for structured JSONrequests to preserve the completion allowance.

Because each generation round can itself require one API retry, a difficultrequest may use more than one DeepSeek API call.

Translate text

Open Translate text.

Paste a short source text.

Enter the source language.

Enter a reliable attribution, or leave it blank to useUser-supplied text.

Request the translation.

Review the staged Latin and back-translation.

The application does not allow DeepSeek to invent an ancient attribution foruser-supplied text.

Review candidate

Open Review candidate.

Select a staged candidate.

Ask DeepSeek to review it.

Examine:

Latin assessment;

translation assessment;

attribution assessment;

source assessment;

secularity assessment;

recommended action;

proposed corrections; and

review status.

A proposed correction becomes a separate unreviewed candidate. It does notoverwrite or approve the original.

Review statuses:

unreviewed: no saved AI review;

pass: no issue identified by the AI review;

caution: requires an explicit override before library addition; and

reject: cannot be added to the library.

AI pass does not replace independent source verification.

Backfill legacy metadata

Older staged candidates may show:

blank primary theme;

unknown source period; or

unverified source confidence.

Expand Legacy candidate metadata maintenance:

confirm that the operation uses the DeepSeek API;

select Backfill missing metadata;

review the returned metadata; and

repeat if more than ten candidates require updates.

The operation updates at most ten candidates per request and does not changetheir Latin, translation, or attribution. Low-confidence candidates are markedcaution.

Approving AI candidates

Review the candidate table.

Check review_status, source_confidence, policy_warning, andduplicate_warning.

Independently verify the source and Latin.

Select add to library for acceptable candidates.

If a candidate is marked caution, enable the explicit caution override.

Select Add selected candidates as unapproved.

Review the new library entries.

Approve them only after verification.

Select Save sayings.

reject candidates cannot be added.

Scheduling

Open Schedule and configure:

minimum posts per week;

maximum posts per week;

allowed weekdays;

earliest posting time;

latest posting time;

schedule horizon in days;

minimum spacing in hours;

maximum post characters;

LinkedIn visibility; and

dry-run mode.

Visibility options:

PUBLIC

CONNECTIONS

Select Save schedule settings, then Fill randomized schedule.

The scheduler:

randomizes eligible days and times;

respects the configured timezone;

respects minimum spacing;

avoids two active queue entries for the same saying;

rotates through approved material before recent reuse;

accounts for already queued and recently posted entries; and

stops adding entries when there is not enough eligible approved content.

Dry-run and live automation

Dry-run

When dry-run is on:

the queue can be generated and inspected;

scheduled items are not published; and

automation cannot be enabled.

Going live

Pause automation.

Review approved sayings.

Cancel obsolete queued items.

Save schedule settings.

Fill and inspect the randomized queue.

Confirm LinkedIn is connected.

Turn dry-run off.

Save schedule settings again.

Select Enable automation.

Pausing

Select Pause automation whenever changing:

content;

approvals;

visibility;

posting frequency;

posting days;

time windows; or

tokens and credentials.

Dashboard and posting statuses

The Dashboard displays:

automation state;

LinkedIn connection state;

queued count;

items needing review;

dry-run status;

worker heartbeat; and

the current posting queue.

Common queue statuses:

queued

publishing

posted

failed

needs_review

dismissed

If the process stops after claiming a post but before saving the result, an itemleft in publishing for more than ten minutes is moved to needs_review whenthe worker restarts.

Always check LinkedIn directly before resolving an uncertain post. Do notblindly retry it, because LinkedIn may have accepted the original request evenif the response was interrupted.

LinkedIn token renewal

The LinkedIn access token expires on the date shown in LinkedIn and setup.The current LinkedIn developer configuration may issue a token lastingapproximately two months, but the displayed expiry is the authoritative value.

When the token expires:

LinkedIn is marked disconnected; and

automation is paused.

To renew:

Pause automation.

Open LinkedIn and setup.

Select Prepare LinkedIn connection.

Select Continue to LinkedIn.

Authorize the application again.

Confirm the new connected state and expiry.

Inspect the queue.

Re-enable automation only when ready.

The new encrypted token replaces the old one.

Updating the application

Pause automation.

Keep a local copy of the currently working code.

Replace streamlit_app.py in the main GitHub branch.

Confirm that requirements.txt is still correct.

Commit the change.

Allow Streamlit to restart.

Confirm the displayed application version.

Confirm GitHub state loads.

Confirm LinkedIn remains connected.

Confirm approved sayings, queue, history, and settings remain present.

Keep dry-run on while testing changed scheduling or posting behavior.

Application updates preserve runtime state because it is maintained separatelyon the runtime-state branch.

Secret rotation

Administrator password

Replace ADMIN_PASSWORD in Streamlit Secrets and save. Existing Streamlitsessions may need to sign in again after restart.

GitHub token

Create a replacement fine-grained token.

Give it repository Contents read/write access.

Replace GITHUB_STATE_TOKEN.

Restart the app.

Confirm state can load and save.

Revoke the old token.

LinkedIn client secret

Generate a new secret in the LinkedIn developer application.

Replace LINKEDIN_CLIENT_SECRET.

Restart the app.

Reconnect LinkedIn if required.

Remove the old secret when safe.

Fernet key

Avoid rotating the Fernet key unless necessary. If it changes, the existingLinkedIn token cannot be decrypted.

To rotate:

Pause automation.

replace FERNET_KEY.

Restart the app.

Reconnect LinkedIn.

Confirm the new token can be used.

DeepSeek key

Replace DEEPSEEK_API_KEY and restart. Existing sayings, candidates, andLinkedIn functionality remain available.

Troubleshooting

The app remains “in the oven”

Open Manage app.

Inspect the logs.

Confirm Python 3.12 is selected.

Confirm requirements.txt is present.

Correct the first dependency or syntax error.

Reboot the app once.

Python 3.14 caused slow dependency processing during initial testing. Python3.12 launched the application successfully.

Configuration required

Add every required secret using valid TOML syntax. Confirm:

each key appears once;

strings are quoted;

multiline accidental wrapping has not split a token;

the GitHub repository uses username/repository; and

no placeholder text remains.

GitHub state cannot initialize

Confirm:

the token has not expired;

it is scoped to the correct repository;

Contents is Read and write;

Metadata is Read-only;

the repository name matches exactly; and

the resource owner is correct.

LinkedIn redirect mismatch

Confirm the same exact URL appears in:

LinkedIn developer application, Auth, authorized redirect URLs; and

Streamlit Secrets, LINKEDIN_REDIRECT_URI.

Check the trailing slash.

LinkedIn is disconnected or returns 401

Reconnect LinkedIn. Confirm the products remain provisioned and the scopesinclude:

openid
profile
w_member_social

LinkedIn returns an uncertain result

Check the member profile directly. Resolve the item manually from the Dashboardonly after confirming whether the post exists.

Stored credential cannot be decrypted

Restore the original FERNET_KEY. If the key was intentionally replaced,reconnect LinkedIn.

DeepSeek 401

Replace the API key.

DeepSeek 402

Check the DeepSeek account balance.

DeepSeek 429

Wait and retry later.

DeepSeek truncation or malformed JSON

The app automatically retries once with a larger generated-output allowance.If the retry fails:

request fewer candidates;

simplify the theme request; or

try again later.

Fewer candidates are staged than requested

Review the generation notes. The app already attempted replacements. Commonreasons include:

prohibited wording;

duplicate Latin;

missing metadata;

wrong source language;

off-theme classification; and

malformed model output.

Valid partial results remain staged for review.

Arabic results are missing

Use:

Source-language mode: One required source language
Required source language: Arabic

Do not rely on the preferences-only mode to guarantee Arabic coverage.

Balanced coverage is rejected

The number of candidates must be at least the number of preferred languages.

For four languages, request at least four candidates.

An older candidate shows unknown metadata

Use Legacy candidate metadata maintenance. The operation updates at most tencandidates per request.

A candidate is unexpectedly rejected

Read policy_warning. It identifies the scanned field and exact matchedwording. Internal notes are not scanned.

Queue does not contain enough posts

Confirm:

enough sayings are approved;

allowed weekdays cover the requested frequency;

the schedule horizon is long enough;

minimum spacing is not too large;

the time window is valid; and

existing queue and history entries are not occupying the available slots.

App hibernation delays a post

Confirm the app-waker contains the deployed URL. Treat Community Cloud timing asbest effort. For stronger timing guarantees, move the worker to a dedicatedalways-on scheduler or hosting service.

Security and privacy notes

Keep all secrets in Streamlit Secrets.

Never commit API keys, tokens, passwords, or the Fernet key.

Scope the GitHub token to one repository.

Use a private repository when practical.

Treat the runtime-state branch as operational data.

DeepSeek receives the candidate-generation prompts and a compact list ofexisting Latin and attributions for duplicate avoidance.

DeepSeek does not receive the LinkedIn token, GitHub token, administratorpassword, or Fernet key.

LinkedIn receives only OAuth requests and the post payloads submitted throughits API.

The LinkedIn access token is encrypted before it is written to GitHub state.

Encryption protects the token but does not make a public runtime-state branchequivalent to private storage.

Revoke and replace any credential that is accidentally exposed.

Operational limitations

Streamlit Community Cloud can hibernate or restart.

The in-process worker has no guaranteed service-level agreement.

Scheduled times are approximate.

LinkedIn API access, products, scopes, and token policies can change.

DeepSeek output can be incorrect or incomplete.

AI source citations require independent verification.

A language model cannot guarantee classical-text accuracy.

The local secular-language filter is conservative and not linguisticallyexhaustive.

The app currently posts to a connected member profile, not a company Page.

The app currently supports the Latin-sayings workflow, not arbitrary posttemplates, images, documents, or campaigns.

Recommended future enhancements

Once the current workflow is stable, possible extensions include:

general LinkedIn text-post templates;

multiple reviewed content libraries;

topic-specific campaigns;

optional images or document posts, subject to LinkedIn API access;

per-content-type schedules;

an accessible privacy-policy page;

stronger source-verification workflows;

an always-on external worker;

encrypted database-backed state;

notification of token expiry and posting failures; and

a formal automated test suite separated from the monolithic application.

Any broader posting feature should retain the current review, dry-run, queue,visibility, token, duplicate, and uncertain-result safeguards.

Support and feedback

For questions, defects, or suggestions, open a GitHub Issue. For proposed codeor documentation changes, open a Pull Request.

Do not include credentials, access tokens, personal data, or private LinkedIncontent in an Issue or Pull Request.
