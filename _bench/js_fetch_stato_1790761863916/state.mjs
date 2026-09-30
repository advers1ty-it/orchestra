export const descrizione = (stato) => {
    switch (stato) {
        case 'ok':
            return 'tutto bene';
        case 'errore':
            return 'qualcosa è andato storto';
        default:
            return 'non so';
    }
};

console.log(descrizione('errore'));
