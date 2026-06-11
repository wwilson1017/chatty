import js from '@eslint/js'
import globals from 'globals'
import reactHooks from 'eslint-plugin-react-hooks'
import reactRefresh from 'eslint-plugin-react-refresh'
import tseslint from 'typescript-eslint'
import { defineConfig, globalIgnores } from 'eslint/config'

export default defineConfig([
  globalIgnores(['dist']),
  {
    files: ['**/*.{ts,tsx}'],
    extends: [
      js.configs.recommended,
      tseslint.configs.recommended,
      reactHooks.configs.flat.recommended,
      reactRefresh.configs.vite,
    ],
    languageOptions: {
      ecmaVersion: 2020,
      globals: globals.browser,
    },
    rules: {
      // Native dialogs are replaced by shared/toast.ts and shared/confirm.ts.
      'no-alert': 'error',
      'no-restricted-globals': [
        'error',
        { name: 'confirm', message: 'Use confirmDialog() from shared/confirm instead.' },
        { name: 'alert', message: 'Use toast from shared/toast instead.' },
        { name: 'prompt', message: 'Use a styled input dialog instead.' },
      ],
    },
  },
])
