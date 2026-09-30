function descrizione(stato) {
  switch (stato) {
    case 'ok':
      return 'tutto bene';
    case 'errore':
      return 'qualcosa e\' andato storto';
    default:
      return 'non so';
  }
}

console.log(descrizione('errore'));
