#!/usr/bin/env node
/**
 * JARVIS publish pipeline.
 *
 *   1. Compiles the Python backend into a single binary (PyInstaller)
 *   2. Builds the native installer for the current OS:
 *        - Linux  -> AppImage
 *        - Windows-> NSIS wizard installer (.exe)
 *   3. Tags the release (v<version>), pushes the tag (triggers GitHub Actions,
 *      which builds the Windows installer on a real Windows runner)
 *   4. Creates a DRAFT GitHub release and uploads the local installer(s)
 *
 * Requirements: gh CLI authenticated (gh auth login), git, python venv.
 *
 * Usage:
 *   npm run publish          (Linux or Windows)
 */

const { execSync } = require('child_process');
const fs = require('fs');
const path = require('path');

const ROOT = path.resolve(__dirname, '..');
const ELECTRON = path.join(ROOT, 'electron');
const VENV_PY = process.platform === 'win32'
  ? path.join(ROOT, 'venv', 'Scripts', 'python.exe')
  : path.join(ROOT, 'venv', 'bin', 'python');

function sh(cmd, cwd = ROOT) {
  console.log(`\n>> ${cmd}`);
  execSync(cmd, { cwd, stdio: 'inherit', shell: true });
}

function check(cmd) {
  try {
    execSync(cmd, { stdio: 'pipe', shell: true });
    return true;
  } catch {
    return false;
  }
}

function main() {
  // --- preflight ---
  if (!check('gh auth status')) {
    console.error('[ERROR] gh CLI not authenticated. Run: gh auth login');
    process.exit(1);
  }
  if (!fs.existsSync(VENV_PY)) {
    console.error(`[ERROR] venv not found at ${VENV_PY}. Create it first (see README).`);
    process.exit(1);
  }

  const pkg = JSON.parse(fs.readFileSync(path.join(ELECTRON, 'package.json'), 'utf8'));
  const version = pkg.version;
  const tag = `v${version}`;
  console.log(`\n[STEP] JARVIS publish ${version} on ${process.platform}`);

  // --- 1. backend binary ---
  sh(`${JSON.stringify(VENV_PY)} scripts/build_backend.py`);

  // --- 2. installer for the current OS (never auto-publish; gh CLI uploads) ---
  const targets = process.platform === 'win32'
    ? ['--win', 'nsis', '--publish', 'never']
    : ['--linux', 'AppImage', '--publish', 'never'];
  sh(`npx electron-builder ${targets.join(' ')}`, ELECTRON);

  // --- 3. tag + push (triggers CI for the Windows build on Linux machines) ---
  if (!check(`git rev-parse ${tag}`)) {
    sh(`git tag ${tag} && git push origin ${tag}`);
  } else {
    console.log(`Tag ${tag} already exists.`);
  }

  // --- 4. draft release + upload local artifacts ---
  const distDir = path.join(ELECTRON, 'dist');
  // installers + auto-update metadata (latest*.yml, *.blockmap)
  const RELEVANT = /\.(exe|AppImage|blockmap)$|^latest(-linux|-mac)?\.yml$/;
  const files = fs.readdirSync(distDir).filter((f) => RELEVANT.test(f));
  if (!files.some((f) => /\.(exe|AppImage)$/.test(f))) {
    console.error('[ERROR] no installer artifact found in electron/dist');
    process.exit(1);
  }

  if (!check(`gh release view ${tag}`)) {
    sh(`gh release create --draft ${tag} --title "JARVIS ${version}" --generate-notes`);
  }

  for (const f of files) {
    sh(`gh release upload ${tag} ${JSON.stringify(path.join(distDir, f))} --clobber`);
  }

  console.log(`\n[OK] Draft release ready: https://github.com/${process.env.GITHUB_REPOSITORY || 'your-org/jarvis'}/releases/tag/${tag}`);
  console.log('   GitHub Actions is building the Windows installer in the background; it will be attached automatically.');
}

main();
