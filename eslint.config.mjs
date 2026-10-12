export default [{
  files: ['prototype/*.js', 'prototype/*.cjs', 'tests/*.cjs'],
  languageOptions: { ecmaVersion: 'latest', sourceType: 'script', globals: Object.fromEntries(['innerWidth','process','require','module','__dirname','console','document','Image','ImageData','FileReader','setTimeout','Tweak'].map(name=>[name,'readonly'])) },
  rules: { 'no-undef':'error', 'no-unused-vars':['error',{caughtErrors:'none'}], 'no-unreachable':'error', 'no-constant-condition':'error', 'no-dupe-args':'error', 'no-dupe-keys':'error', 'valid-typeof':'error' }
}];
