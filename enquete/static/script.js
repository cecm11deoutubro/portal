// Exemplo: Validação de formulário de voto
document.addEventListener('DOMContentLoaded', function() {
    const voteForms = document.querySelectorAll('form[action*="vote"]');
    voteForms.forEach(form => {
        form.addEventListener('submit', function(e) {
            const selected = form.querySelector('input[type="radio"]:checked');
            if (!selected) {
                alert('Selecione uma opção!');
                e.preventDefault();
            }
        });
    });
});