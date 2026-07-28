// Planted: ESLint no-unused-vars when repo eslint config is honored (catalog C1)
const plantedUnusedBinding = "eslint-config-dependent";

function greet(name) {
  return `hello ${name}`;
}

module.exports = { greet };
